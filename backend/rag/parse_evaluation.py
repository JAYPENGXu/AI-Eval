from __future__ import annotations
import statistics
import time
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from .document_parsing.parsers import garbled_character_rate, get_parser, markdown_page, non_whitespace_count
from .document_parsing.paddleocr import PaddleOcrClient
from .document_parsing.service import _make_ocr_subset, _ocr_candidates
from .models import DocumentParseBenchmarkCase, DocumentParseEvalCaseResult, DocumentParseEvalRun


def _ratio(expected, actual):
    expected, actual = set(expected), set(actual)
    if not expected: return 1.0
    return len(expected & actual) / len(expected)


def evaluate_case(case):
    started = time.perf_counter()
    parser = get_parser(Path(case.file.name).suffix.lower().lstrip("."))
    path = Path(case.file.path)
    ir = parser.parse(path, mime_type="", title=case.title)
    candidates = _ocr_candidates(ir) if path.suffix.lower() == ".pdf" else []
    if candidates:
        subset = _make_ocr_subset(path, candidates)
        try:
            markdown_pages = PaddleOcrClient().parse(subset)
        finally:
            subset.unlink(missing_ok=True)
        if len(markdown_pages) != len(candidates):
            raise ValueError(f"PaddleOCR page count mismatch: expected {len(candidates)}, got {len(markdown_pages)}.")
        for page_index, markdown in zip(candidates, markdown_pages):
            ir.pages[page_index] = markdown_page(markdown, page_index + 1, extraction_method="ocr")
    pages = ir.pages
    ocr_pages = [p.page_number for p in pages if p.extraction_method == "ocr"]
    expected_ocr = [int(v) for v in (case.expected_ocr_pages or [])]
    tp = len(set(ocr_pages) & set(expected_ocr))
    precision = tp / len(ocr_pages) if ocr_pages else (1.0 if not expected_ocr else 0.0)
    recall = tp / len(expected_ocr) if expected_ocr else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    headings = [block.text for page in pages for block in page.blocks if block.type == "heading"]
    block_types = [block.type for page in pages for block in page.blocks]
    all_text = "\n".join(page.text for page in pages)
    terms_checks = {}
    for page, terms in (case.expected_terms_by_page or {}).items():
        number = int(page)
        text = next((p.text for p in pages if p.page_number == number), "").lower()
        terms_checks[str(number)] = {term: str(term).lower() in text for term in terms}
    thresholds = {"min_heading_recall": 1.0, "min_term_recall": 1.0, "max_garbled_rate": settings.DOCUMENT_REVIEW_MAX_GARBLED_RATE, "max_duration_ms": settings.CELERY_TASK_TIME_LIMIT * 1000, **(case.thresholds or {})}
    heading_recall = _ratio([str(v).lower() for v in case.expected_headings or []], [v.lower() for v in headings])
    term_values = [passed for page in terms_checks.values() for passed in page.values()]
    term_recall = sum(term_values) / len(term_values) if term_values else 1.0
    garbled = garbled_character_rate(all_text)
    duration = round((time.perf_counter() - started) * 1000)
    checks = {
        "page_count": case.expected_page_count is None or len(pages) == case.expected_page_count,
        "ocr_pages": f1 >= float(thresholds.get("min_ocr_f1", 1.0)),
        "headings": heading_recall >= float(thresholds["min_heading_recall"]),
        "page_terms": term_recall >= float(thresholds["min_term_recall"]),
        "block_types": set(case.expected_block_types or []).issubset(set(block_types)),
        "table_terms": all(str(term).lower() in all_text.lower() for term in case.expected_table_terms or []),
        "garbled_rate": garbled <= float(thresholds["max_garbled_rate"]),
        "duration": duration <= int(thresholds["max_duration_ms"]),
    }
    metrics = {"page_count": len(pages), "ocr_pages": ocr_pages, "ocr_precision": round(precision, 4), "ocr_recall": round(recall, 4), "ocr_f1": round(f1, 4), "heading_recall": round(heading_recall, 4), "term_recall": round(term_recall, 4), "garbled_character_rate": round(garbled, 6), "total_chars": non_whitespace_count(all_text), "block_types": sorted(set(block_types)), "page_term_checks": terms_checks}
    return all(checks.values()), metrics, checks, duration


def execute_parse_eval_run(run_id):
    run = DocumentParseEvalRun.objects.get(id=run_id)
    if run.status not in {"queued", "running"}: return
    run.status = "running"; run.started_at = timezone.now(); run.error_message = ""
    run.save(update_fields=["status", "started_at", "error_message"])
    cases = list(DocumentParseBenchmarkCase.objects.filter(owner=run.owner, suite=run.suite, enabled=True))
    durations=[]; passed_count=0
    try:
        run.case_results.all().delete()
        for case in cases:
            try:
                passed, metrics, checks, duration = evaluate_case(case)
                DocumentParseEvalCaseResult.objects.create(run=run, case=case, passed=passed, metrics=metrics, checks=checks, duration_ms=duration)
            except Exception as exc:
                passed=False; duration=0
                DocumentParseEvalCaseResult.objects.create(run=run, case=case, passed=False, error_message=str(exc))
            durations.append(duration); passed_count += int(passed)
        ordered=sorted(durations)
        p95=ordered[min(len(ordered)-1, round((len(ordered)-1)*.95))] if ordered else 0
        run.case_count=len(cases); run.passed_count=passed_count
        run.summary={"pass_rate": round(passed_count/len(cases),4) if cases else 0, "p50_duration_ms": statistics.median(durations) if durations else 0, "p95_duration_ms": p95}
        run.status="completed"; run.finished_at=timezone.now()
        run.save(update_fields=["case_count","passed_count","summary","status","finished_at"])
    except Exception as exc:
        run.status="failed"; run.error_message=str(exc); run.finished_at=timezone.now()
        run.save(update_fields=["status","error_message","finished_at"])
        raise
