from __future__ import annotations
import hashlib
import json
import logging
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .indexing import resolve_parse_run
from .models import DocumentIndexRun
logger = logging.getLogger(__name__)
INDEX_SCHEMA_VERSION = "2"


def build_index_manifest(document, parse_run, method, options):
    return {"file_sha256": document.sha256, "parse_run_id": parse_run.id, "parser": parse_run.parser, "parser_version": parse_run.parser_version, "chunk_method": method, "chunk_options": options or {}, "embedding_model": settings.EMBEDDING_MODEL, "embedding_dimensions": int(settings.EMBEDDING_DIMENSIONS), "vector_backend": "milvus", "vector_collection": settings.MILVUS_COLLECTION, "index_schema_version": INDEX_SCHEMA_VERSION}


def sign_manifest(manifest):
    return hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def index_health(document):
    reasons = []
    manifest = document.index_manifest or {}
    latest = document.parse_runs.filter(status="completed").order_by("-created_at", "-id").first()
    if not document.index_signature or not manifest: reasons.append({"code": "missing_manifest", "severity": "warning", "message": "旧索引缺少版本签名，请重建。"})
    if latest and manifest.get("parse_run_id") != latest.id: reasons.append({"code": "newer_parse_run", "severity": "warning", "message": "存在更新的解析结果。"})
    for key, current in {"embedding_model": settings.EMBEDDING_MODEL, "vector_collection": settings.MILVUS_COLLECTION, "index_schema_version": INDEX_SCHEMA_VERSION}.items():
        if manifest and str(manifest.get(key)) != str(current): reasons.append({"code": f"{key}_changed", "severity": "warning", "message": f"{key} 已变化。"})
    if manifest and int(manifest.get("embedding_dimensions") or 0) != int(settings.EMBEDDING_DIMENSIONS): reasons.append({"code": "embedding_dimensions_changed", "severity": "critical", "message": "Embedding 维度与现有索引不兼容。"})
    critical = any(item["severity"] == "critical" for item in reasons)
    return {"document_id": document.id, "status": document.status, "signature": document.index_signature, "stale": bool(reasons), "critical": critical, "reasons": reasons, "usable": document.chunks.exists() and not critical}


def create_index_run(document, method, options, parse_run_id=None):
    parse_run = resolve_parse_run(document, parse_run_id)
    manifest = build_index_manifest(document, parse_run, method, options)
    signature = sign_manifest(manifest)
    with transaction.atomic():
        active = DocumentIndexRun.objects.select_for_update().filter(document=document, status__in=["queued", "running"], target_signature=signature).first()
        if active: return active
        run = DocumentIndexRun.objects.create(document=document, parse_run=parse_run, chunk_method=method, chunk_options=options or {}, target_manifest=manifest, target_signature=signature)
        transaction.on_commit(lambda: enqueue_index_run(run.id))
        return run


def enqueue_index_run(run_id):
    from .tasks import index_document_task
    try:
        result = index_document_task.apply_async(args=[run_id], queue="documents")
        DocumentIndexRun.objects.filter(id=run_id, status="queued").update(celery_task_id=result.id)
    except Exception as exc:
        message = f"索引任务无法进入队列，请检查 Celery/Redis：{exc}"
        DocumentIndexRun.objects.filter(id=run_id).update(status="failed", error_message=message, finished_at=timezone.now())
        logger.exception("index enqueue failed run=%s", run_id)
        raise RuntimeError(message) from exc
