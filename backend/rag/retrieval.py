from __future__ import annotations

import logging
import math
from typing import Iterable

from django.conf import settings

from .indexing import embed_texts
from .models import Chunk, KnowledgeBase
from .source_metadata import source_location
from .vector_store import get_vector_store

logger = logging.getLogger(__name__)


def cosine(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = list(left)
    right_values = list(right)
    dot = sum(a * b for a, b in zip(left_values, right_values))
    left_norm = math.sqrt(sum(a * a for a in left_values))
    right_norm = math.sqrt(sum(b * b for b in right_values))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0


def format_source(chunk: Chunk, score: float, rank: int, engine: str) -> dict:
    return {
        "rank": rank,
        "chunk_id": chunk.id,
        "document": chunk.document.filename,
        "score": score,
        "engine": engine,
        "content": chunk.content,
        "metadata": chunk.metadata,
        "location": source_location(chunk.metadata),
    }


def retrieve_with_sqlite(kb: KnowledgeBase, query_embedding: list[float], top_k: int) -> list[dict]:
    scored = []
    for chunk in Chunk.objects.filter(kb=kb).exclude(embedding__isnull=True).select_related("document"):
        scored.append((cosine(query_embedding, chunk.embedding), chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        format_source(chunk, score, rank, "sqlite_vector_fallback")
        for rank, (score, chunk) in enumerate(scored[:top_k], start=1)
    ]


def retrieve(kb: KnowledgeBase, question: str, top_k: int | None = None, context: dict | None = None) -> list[dict]:
    query_embedding = embed_texts([question], call_type="embedding_query", owner=kb.owner, kb=kb, **(context or {}))[0]
    limit = top_k or settings.RAG_TOP_K
    try:
        vector_hits = get_vector_store().search(kb, query_embedding, limit)
    except Exception as exc:
        logger.warning("milvus vector search failed kb=%s error=%s", kb.id, exc)
        vector_hits = []

    if vector_hits:
        chunk_map = {
            chunk.id: chunk
            for chunk in Chunk.objects.filter(id__in=[hit["chunk_id"] for hit in vector_hits]).select_related("document")
        }
        results = []
        for hit in vector_hits:
            chunk = chunk_map.get(hit["chunk_id"])
            if not chunk:
                continue
            results.append(format_source(chunk, hit["score"], hit["rank"], hit["engine"]))
        return results

    return retrieve_with_sqlite(kb, query_embedding, limit)
