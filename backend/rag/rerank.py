from __future__ import annotations

import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

from .model_usage import elapsed_ms, record_model_call


def rerank_candidates(
    question: str,
    candidates: list[dict],
    top_n: int | None = None,
    candidate_n: int | None = None,
    context: dict | None = None,
) -> list[dict]:
    limit = top_n or settings.RERANK_TOP_N
    candidate_limit = candidate_n or settings.RERANK_CANDIDATE_N
    selected = candidates[:candidate_limit]
    if not selected:
        return []
    if not settings.RERANK_ENABLED:
        return fallback_rerank(selected, limit, "rerank_disabled")

    try:
        return dashscope_rerank(question, selected, limit, context=context)
    except Exception as exc:
        logger.warning("rerank failed fallback=%s", exc)
        return fallback_rerank(selected, limit, "rerank_fallback")


def dashscope_rerank(question: str, candidates: list[dict], top_n: int, context: dict | None = None) -> list[dict]:
    documents = [candidate["content"] for candidate in candidates]
    started_at = time.perf_counter()
    response = requests.post(
        settings.RERANK_API_URL,
        headers={
            "Authorization": f"Bearer {settings.API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.RERANK_MODEL,
            "input": {
                "query": question,
                "documents": documents,
            },
            "parameters": {
                "top_n": min(top_n, len(documents)),
                "return_documents": False,
            },
        },
        timeout=settings.RERANK_TIMEOUT,
    )
    try:
        response.raise_for_status()
    except Exception as exc:
        record_model_call(
            call_type="rerank",
            model=settings.RERANK_MODEL,
            provider="dashscope",
            status="failed",
            latency_ms=elapsed_ms(started_at),
            error_message=str(exc),
            metadata={"document_count": len(documents), "query_chars": len(question), "document_chars": sum(len(item) for item in documents)},
            **(context or {}),
        )
        raise
    data = response.json()
    usage = data.get("usage") or data.get("output", {}).get("usage") or {}
    record_model_call(
        call_type="rerank",
        model=settings.RERANK_MODEL,
        provider="dashscope",
        usage=usage,
        latency_ms=elapsed_ms(started_at),
        metadata={"document_count": len(documents), "query_chars": len(question), "document_chars": sum(len(item) for item in documents)},
        **(context or {}),
    )
    raw_results = data.get("output", {}).get("results", [])

    reranked = []
    for rank, result in enumerate(raw_results, start=1):
        index = int(result["index"])
        candidate = candidates[index]
        item = {
            **candidate,
            "rank": rank,
            "score": float(result.get("relevance_score", 0)),
            "rerank_score": float(result.get("relevance_score", 0)),
            "pre_rerank_rank": candidate.get("rank"),
            "pre_rerank_score": candidate.get("score"),
            "engine": "dashscope_rerank",
            "rerank_model": settings.RERANK_MODEL,
        }
        reranked.append(item)
    return reranked


def fallback_rerank(candidates: list[dict], top_n: int, engine: str) -> list[dict]:
    results = []
    for rank, candidate in enumerate(candidates[:top_n], start=1):
        results.append(
            {
                **candidate,
                "rank": rank,
                "score": candidate.get("score", 0),
                "rerank_score": candidate.get("score", 0),
                "pre_rerank_rank": candidate.get("rank"),
                "pre_rerank_score": candidate.get("score"),
                "engine": engine,
                "rerank_model": settings.RERANK_MODEL,
            }
        )
    return results
