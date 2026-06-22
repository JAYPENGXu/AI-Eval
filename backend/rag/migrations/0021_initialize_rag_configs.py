import hashlib
import json
from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    KnowledgeBase = apps.get_model("rag", "KnowledgeBase")
    Version = apps.get_model("rag", "RagConfigVersion")
    payload = {
        "query_rewrite_strategy": getattr(settings, "QUERY_REWRITE_STRATEGY", "rule"),
        "top_k": settings.RAG_TOP_K, "bm25_top_k": settings.BM25_TOP_K,
        "hybrid_top_k": settings.HYBRID_TOP_K, "rrf_k": settings.RRF_K,
        "rerank_top_n": settings.RERANK_TOP_N, "rerank_candidate_n": settings.RERANK_CANDIDATE_N,
        "compression_strategy": settings.CONTEXT_COMPRESSION_STRATEGY,
    }
    signature = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    for kb in KnowledgeBase.objects.filter(active_config_version__isnull=True):
        version = Version.objects.create(kb=kb, version=1, payload=payload, signature=signature, source="initial", validation_status="release_passed", created_by_id=kb.owner_id)
        kb.active_config_version_id = version.id
        kb.save(update_fields=["active_config_version"])


class Migration(migrations.Migration):
    dependencies = [("rag", "0020_chatsessionsummary_celery_task_id_and_more")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
