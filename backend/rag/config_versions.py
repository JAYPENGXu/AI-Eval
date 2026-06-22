from __future__ import annotations

import hashlib
import json

from django.conf import settings
from django.db import transaction
from django.db.models import Max

from .models import KnowledgeBase, RagConfigDeployment, RagConfigVersion

PUBLISHABLE_KEYS = {"query_rewrite_strategy", "top_k", "bm25_top_k", "hybrid_top_k", "rrf_k", "rerank_top_n", "rerank_candidate_n", "compression_strategy"}
INTEGER_LIMITS = {"top_k": (1, 20), "bm25_top_k": (1, 20), "hybrid_top_k": (1, 40), "rrf_k": (1, 200), "rerank_top_n": (1, 20), "rerank_candidate_n": (1, 50)}
ALLOWED_REWRITE = {"none", "rule", "llm"}
ALLOWED_COMPRESSION = {"none", "sentence_filter", "structure_aware", "llm"}


def default_config():
    return {"query_rewrite_strategy": getattr(settings, "QUERY_REWRITE_STRATEGY", "rule"), "top_k": settings.RAG_TOP_K, "bm25_top_k": settings.BM25_TOP_K, "hybrid_top_k": settings.HYBRID_TOP_K, "rrf_k": settings.RRF_K, "rerank_top_n": settings.RERANK_TOP_N, "rerank_candidate_n": settings.RERANK_CANDIDATE_N, "compression_strategy": settings.CONTEXT_COMPRESSION_STRATEGY}


def normalize_config(payload, *, base=None):
    result = {**default_config(), **(base or {})}
    for key, value in (payload or {}).items():
        if key not in PUBLISHABLE_KEYS:
            continue
        if key in INTEGER_LIMITS:
            low, high = INTEGER_LIMITS[key]
            try: value = int(value)
            except (TypeError, ValueError) as exc: raise ValueError(f"{key} must be an integer.") from exc
            value = min(max(value, low), high)
        result[key] = value
    if result["query_rewrite_strategy"] not in ALLOWED_REWRITE: raise ValueError("Unsupported query_rewrite_strategy.")
    if result["compression_strategy"] not in ALLOWED_COMPRESSION: raise ValueError("Unsupported compression_strategy.")
    result["rerank_candidate_n"] = max(result["rerank_candidate_n"], result["rerank_top_n"])
    return {key: result[key] for key in sorted(PUBLISHABLE_KEYS)}


def config_signature(payload):
    raw = json.dumps(normalize_config(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_initial_config(kb, user=None):
    if kb.active_config_version_id: return kb.active_config_version
    with transaction.atomic():
        locked = KnowledgeBase.objects.select_for_update().get(id=kb.id)
        if locked.active_config_version_id: return locked.active_config_version
        payload = normalize_config({})
        version = RagConfigVersion.objects.create(kb=locked, version=1, payload=payload, signature=config_signature(payload), source="initial", validation_status="release_passed", created_by=user or locked.owner)
        locked.active_config_version = version
        locked.save(update_fields=["active_config_version", "updated_at"])
        return version


def create_config_version(*, kb, payload, user, source="manual", parent=None, **links):
    normalized = normalize_config(payload, base=(parent.payload if parent else None))
    with transaction.atomic():
        locked = KnowledgeBase.objects.select_for_update().get(id=kb.id)
        next_version = (RagConfigVersion.objects.filter(kb=locked).aggregate(v=Max("version"))["v"] or 0) + 1
        return RagConfigVersion.objects.create(kb=locked, version=next_version, payload=normalized, signature=config_signature(normalized), source=source, parent=parent, created_by=user, **links)


def resolve_runtime_config(kb, override=None, *, override_enabled=False):
    active = ensure_initial_config(kb)
    payload = normalize_config(override if override_enabled else {}, base=active.payload)
    return payload, {"config_version_id": active.id, "config_version": active.version, "config_signature": active.signature, "config_source": "temporary_override" if override_enabled and override else "active_config", "temporary_override": {k: v for k, v in (override or {}).items() if k in PUBLISHABLE_KEYS} if override_enabled else {}}


def deploy_config(*, kb, target, user, action=None, operation="publish", reason=""):
    if target.kb_id != kb.id or target.validation_status != "release_passed": raise ValueError("Only release-passed versions in this knowledge base can be deployed.")
    with transaction.atomic():
        locked = KnowledgeBase.objects.select_for_update().get(id=kb.id)
        previous = locked.active_config_version
        if previous and previous.id == target.id:
            return RagConfigDeployment.objects.filter(kb=locked, target_version=target).order_by("-id").first()
        deployment = RagConfigDeployment.objects.create(kb=locked, previous_version=previous, target_version=target, action=action, operation=operation, reason=reason, deployed_by=user)
        locked.active_config_version = target
        locked.save(update_fields=["active_config_version", "updated_at"])
        return deployment
