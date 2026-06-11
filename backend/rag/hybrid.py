from __future__ import annotations

from django.conf import settings


def rrf_fusion(
    bm25_results: list[dict],
    vector_results: list[dict],
    top_k: int | None = None,
    rrf_k: int | None = None,
) -> list[dict]:
    limit = top_k or settings.HYBRID_TOP_K
    fusion_k = rrf_k or settings.RRF_K
    fused: dict[int, dict] = {}

    add_ranked_results(fused, bm25_results, "bm25", fusion_k)
    add_ranked_results(fused, vector_results, "vector", fusion_k)

    results = list(fused.values())
    results.sort(key=lambda item: item["rrf_score"], reverse=True)
    for rank, item in enumerate(results[:limit], start=1):
        item["rank"] = rank
        item["score"] = item["rrf_score"]
        item["engine"] = "hybrid_rrf"
    return results[:limit]


def add_ranked_results(fused: dict[int, dict], results: list[dict], source: str, rrf_k: int) -> None:
    for fallback_rank, item in enumerate(results, start=1):
        rank = int(item.get("rank") or fallback_rank)
        chunk_id = int(item["chunk_id"])
        current = fused.setdefault(
            chunk_id,
            {
                **item,
                "rrf_score": 0.0,
                "sources": {},
            },
        )
        current["rrf_score"] += 1 / (rrf_k + rank)
        current["sources"][source] = {
            "rank": rank,
            "score": item.get("score"),
            "engine": item.get("engine"),
            "matched_terms": item.get("matched_terms", []),
        }
