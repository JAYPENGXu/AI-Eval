from __future__ import annotations

import math
import re
from collections import Counter

from django.conf import settings

from .models import Chunk, KnowledgeBase
from .source_metadata import source_location


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text or "")]


def bm25_search(kb: KnowledgeBase, question: str, top_k: int | None = None) -> list[dict]:
    limit = top_k or settings.BM25_TOP_K
    query_tokens = tokenize(question)
    if not query_tokens:
        return []

    chunks = list(Chunk.objects.filter(kb=kb).select_related("document").order_by("id"))
    if not chunks:
        return []

    docs = [tokenize(chunk.content) for chunk in chunks]
    avgdl = sum(len(doc) for doc in docs) / len(docs)
    document_frequency = Counter()
    for doc in docs:
        document_frequency.update(set(doc))

    scored = []
    for chunk, doc_tokens in zip(chunks, docs):
        term_frequency = Counter(doc_tokens)
        score = 0.0
        matched_terms = []
        for term in query_tokens:
            tf = term_frequency.get(term, 0)
            if not tf:
                continue
            matched_terms.append(term)
            df = document_frequency[term]
            idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
            denominator = tf + settings.BM25_K1 * (1 - settings.BM25_B + settings.BM25_B * len(doc_tokens) / avgdl)
            score += idf * (tf * (settings.BM25_K1 + 1)) / denominator
        if score > 0:
            scored.append((score, sorted(set(matched_terms)), chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    for rank, (score, matched_terms, chunk) in enumerate(scored[:limit], start=1):
        item = {
            "rank": rank,
            "chunk_id": chunk.id,
            "document": chunk.document.filename,
            "score": score,
            "engine": "bm25",
            "content": chunk.content,
            "metadata": chunk.metadata,
            "location": source_location(chunk.metadata),
        }
        item["matched_terms"] = matched_terms
        results.append(item)
    return results
