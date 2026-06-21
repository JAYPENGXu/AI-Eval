from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from rag.models import Document, DocumentPage, DocumentParseRun

from .paddleocr import PaddleOcrClient
from .parsers import garbled_character_rate, get_parser, markdown_page, non_whitespace_count

logger = logging.getLogger(__name__)


def create_parse_run(document: Document) -> DocumentParseRun:
    with transaction.atomic():
        active = (
            DocumentParseRun.objects.select_for_update()
            .filter(document=document, status__in=["queued", "running"])
            .order_by("-created_at")
            .first()
        )
        if active:
            return active
        run = DocumentParseRun.objects.create(document=document, status="queued")
        document.status = "queued"
        document.error_message = ""
        document.save(update_fields=["status", "error_message", "updated_at"])
        transaction.on_commit(lambda: enqueue_parse_run(run.id))
        return run


def enqueue_parse_run(run_id: int) -> None:
    from rag.tasks import parse_document_task

    try:
        result = parse_document_task.delay(run_id)
        DocumentParseRun.objects.filter(id=run_id, status="queued").update(celery_task_id=result.id)
    except Exception as exc:
        message = f"解析任务无法进入队列，请检查 Celery/Redis：{exc}"
        DocumentParseRun.objects.filter(id=run_id).update(
            status="failed", error_code="queue_unavailable", error_message=message, finished_at=timezone.now()
        )
        run = DocumentParseRun.objects.filter(id=run_id).select_related("document").first()
        if run:
            Document.objects.filter(id=run.document_id).update(status="failed", error_message=message)
        logger.exception("document parse enqueue failed run=%s", run_id)


def _make_ocr_subset(source_path: Path, page_indexes: list[int]) -> Path:
    import fitz

    target = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    target.close()
    with fitz.open(source_path) as source, fitz.open() as subset:
        for page_index in page_indexes:
            subset.insert_pdf(source, from_page=page_index, to_page=page_index)
        subset.save(target.name, garbage=4, deflate=True)
    return Path(target.name)


def _ocr_candidates(document_ir) -> list[int]:
    candidates = []
    for index, page in enumerate(document_ir.pages):
        text = page.text
        if (
            non_whitespace_count(text) < settings.PDF_NATIVE_TEXT_MIN_CHARS
            or garbled_character_rate(text) > settings.PDF_NATIVE_GARBLED_RATE
        ):
            candidates.append(index)
    return candidates


def _quality_metrics(document_ir, duration_ms: int) -> tuple[dict, float, bool]:
    page_count = len(document_ir.pages)
    texts = [page.text for page in document_ir.pages]
    char_counts = [non_whitespace_count(text) for text in texts]
    nonblank = sum(count >= settings.DOCUMENT_NONBLANK_PAGE_MIN_CHARS for count in char_counts)
    blank = page_count - nonblank
    ocr_pages = sum(page.extraction_method == "ocr" for page in document_ir.pages)
    native_pages = sum(page.extraction_method == "native" and count >= settings.DOCUMENT_NONBLANK_PAGE_MIN_CHARS for page, count in zip(document_ir.pages, char_counts))
    combined_text = "\n".join(texts)
    garbled_rate = garbled_character_rate(combined_text)
    coverage = nonblank / page_count if page_count else 0.0
    native_coverage = native_pages / page_count if page_count else 0.0
    blank_rate = blank / page_count if page_count else 1.0
    failed_rate = 0.0
    metrics = {
        "page_count": page_count,
        "text_coverage_rate": round(coverage, 4),
        "native_text_coverage_rate": round(native_coverage, 4),
        "blank_page_rate": round(blank_rate, 4),
        "ocr_page_rate": round(ocr_pages / page_count, 4) if page_count else 0.0,
        "failed_page_rate": failed_rate,
        "garbled_character_rate": round(garbled_rate, 6),
        "total_chars": sum(char_counts),
        "avg_chars_per_page": round(sum(char_counts) / page_count, 2) if page_count else 0.0,
        "parse_duration_ms": duration_ms,
    }
    garbled_component = 1 - min(garbled_rate / max(settings.DOCUMENT_REVIEW_MAX_GARBLED_RATE, 0.0001), 1)
    score = round(100 * (0.55 * coverage + 0.25 * (1 - blank_rate) + 0.20 * garbled_component), 2)
    needs_review = (
        coverage < settings.DOCUMENT_REVIEW_MIN_COVERAGE
        or blank_rate > settings.DOCUMENT_REVIEW_MAX_BLANK_RATE
        or garbled_rate > settings.DOCUMENT_REVIEW_MAX_GARBLED_RATE
        or failed_rate > 0
    )
    return metrics, score, needs_review


def _update_progress(run_id: int, current: int, total: int) -> None:
    DocumentParseRun.objects.filter(id=run_id, status="running").update(
        progress_current=max(current, 0), progress_total=max(total, 0)
    )


def execute_parse_run(run_id: int, task_id: str = "") -> None:
    started = time.perf_counter()
    with transaction.atomic():
        run = DocumentParseRun.objects.select_for_update().select_related("document").get(id=run_id)
        if run.status == "running" and run.celery_task_id and run.celery_task_id != task_id:
            return
        if run.status not in {"queued", "running"}:
            return
        run.status = "running"
        if task_id:
            run.celery_task_id = task_id
        run.started_at = timezone.now()
        run.error_code = ""
        run.error_message = ""
        run.save(update_fields=[
            "status", "celery_task_id", "started_at", "error_code", "error_message", "updated_at"
        ])
        Document.objects.filter(id=run.document_id).update(status="parsing", error_message="")

    try:
        document = run.document
        parser = get_parser(document.file_type)
        document_ir = parser.parse(Path(document.file.path), mime_type=document.mime_type, title=document.filename)
        run.parser = parser.name
        run.parser_version = parser.version
        run.progress_total = len(document_ir.pages)
        run.save(update_fields=["parser", "parser_version", "progress_total", "updated_at"])

        candidates = _ocr_candidates(document_ir) if document.file_type == "pdf" else []
        if candidates:
            subset_path = _make_ocr_subset(Path(document.file.path), candidates)
            try:
                client = PaddleOcrClient()
                markdown_pages = client.parse(
                    subset_path,
                    progress_callback=lambda current, total: _update_progress(
                        run.id, len(document_ir.pages) - len(candidates) + current, len(document_ir.pages)
                    ),
                    job_callback=lambda job_id: DocumentParseRun.objects.filter(id=run.id).update(provider_job_id=job_id),
                )
            finally:
                subset_path.unlink(missing_ok=True)
            if len(markdown_pages) != len(candidates):
                raise ValueError(
                    f"PaddleOCR 返回 {len(markdown_pages)} 页，但提交了 {len(candidates)} 个扫描页。"
                )
            for page_index, markdown in zip(candidates, markdown_pages):
                original_page = page_index + 1
                document_ir.pages[page_index] = markdown_page(
                    markdown, original_page, extraction_method="ocr"
                )
            document_ir.parser = "pymupdf+paddleocr"
            run.parser = document_ir.parser

        duration_ms = round((time.perf_counter() - started) * 1000)
        metrics, score, needs_review = _quality_metrics(document_ir, duration_ms)
        final_status = "needs_review" if needs_review else "completed"

        with transaction.atomic():
            locked = DocumentParseRun.objects.select_for_update().get(id=run.id)
            has_newer = DocumentParseRun.objects.filter(
                document_id=locked.document_id, created_at__gt=locked.created_at
            ).exclude(status="failed").exists()
            if has_newer:
                locked.status = "superseded"
                locked.finished_at = timezone.now()
                locked.save(update_fields=["status", "finished_at", "updated_at"])
                return
            locked.pages.all().delete()
            DocumentPage.objects.bulk_create([
                DocumentPage(
                    parse_run=locked,
                    page_number=page.page_number,
                    extraction_method=page.extraction_method,
                    text=page.text,
                    markdown=page.markdown,
                    blocks=[block.as_dict() for block in page.blocks],
                    char_count=non_whitespace_count(page.text),
                    is_blank=non_whitespace_count(page.text) < settings.DOCUMENT_NONBLANK_PAGE_MIN_CHARS,
                    metrics=page.metadata,
                )
                for page in document_ir.pages
            ])
            locked.status = final_status
            locked.parser = document_ir.parser
            locked.parser_version = document_ir.parser_version
            locked.progress_current = len(document_ir.pages)
            locked.progress_total = len(document_ir.pages)
            locked.quality_metrics = metrics
            locked.quality_score = score
            locked.finished_at = timezone.now()
            locked.save(update_fields=[
                "status", "parser", "parser_version", "progress_current", "progress_total",
                "quality_metrics", "quality_score", "finished_at", "updated_at",
            ])
            Document.objects.filter(id=locked.document_id).update(
                status="needs_review" if needs_review else "parsed", error_message=""
            )
    except Exception as exc:
        message = str(exc)
        logger.exception("document parsing failed run=%s document=%s", run_id, run.document_id)
        DocumentParseRun.objects.filter(id=run_id).update(
            status="failed", error_code=type(exc).__name__, error_message=message, finished_at=timezone.now()
        )
        newer_exists = DocumentParseRun.objects.filter(
            document_id=run.document_id, created_at__gt=run.created_at
        ).exclude(status="failed").exists()
        if not newer_exists:
            Document.objects.filter(id=run.document_id).update(status="failed", error_message=message)
