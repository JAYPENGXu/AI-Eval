from __future__ import annotations
import time
from pathlib import Path
from celery import current_app
from django.conf import settings
from django.db import connection
from redis import Redis
from .vector_store import get_vector_store


def _check(name, callback, critical=True):
    started = time.perf_counter()
    try: return name, {"ok": True, "critical": critical, "latency_ms": round((time.perf_counter()-started)*1000, 2), "detail": callback()}
    except Exception as exc: return name, {"ok": False, "critical": critical, "latency_ms": round((time.perf_counter()-started)*1000, 2), "error": str(exc)[:300]}


def health_report(detailed=False):
    def database():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1"); return cursor.fetchone()[0]
    def redis(): return Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=1, socket_timeout=1).ping()
    def celery():
        replies = current_app.control.inspect(timeout=1).ping() or {}
        if not replies: raise RuntimeError("No Celery worker replied.")
        return sorted(replies)
    def media():
        root = Path(settings.MEDIA_ROOT); root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir(): raise RuntimeError("MEDIA_ROOT is not a directory.")
        return str(root)
    def vector():
        uri = str(settings.MILVUS_URI)
        if "://" not in uri:
            path = Path(uri)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and not (path.is_file() or path.is_dir()):
                raise RuntimeError("MILVUS_URI is not accessible.")
            return {
                "backend": "milvus_lite",
                "collection": settings.MILVUS_COLLECTION,
                "path": str(path),
                "mode": "local_path_check",
                "path_type": "directory" if path.is_dir() else "file",
            }
        store = get_vector_store()
        store.ensure_collection()
        return {"backend": "milvus", "collection": store.collection_name, "mode": "collection_probe"}
    checks = dict([_check("database", database), _check("redis", redis), _check("celery", celery), _check("media", media), _check("vector", vector)])
    checks["providers"] = {"ok": True, "critical": False, "detail": {"chat_configured": bool(settings.API_KEY and settings.API_BASE), "embedding_configured": bool(settings.API_KEY and settings.EMBEDDING_MODEL), "paddleocr_configured": bool(getattr(settings, "PADDLEOCR_TOKEN", "") and getattr(settings, "PADDLEOCR_JOB_URL", ""))}}
    ready = all(value.get("ok") for value in checks.values() if value.get("critical"))
    return {"status": "ready" if ready else "unavailable", "ready": ready, "checks": checks if detailed else {k: v["ok"] for k, v in checks.items()}}
