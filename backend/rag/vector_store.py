from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from django.conf import settings
from pymilvus import MilvusClient

from .models import Chunk, KnowledgeBase

logger = logging.getLogger(__name__)


class MilvusVectorStore:
    def __init__(self) -> None:
        self.collection_name = settings.MILVUS_COLLECTION
        uri = str(settings.MILVUS_URI)
        if "://" not in uri:
            Path(uri).parent.mkdir(parents=True, exist_ok=True)
        self.client = MilvusClient(uri)
        self._loaded = False

    def ensure_collection(self) -> None:
        if self.client.has_collection(self.collection_name):
            self.load_collection()
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            dimension=settings.EMBEDDING_DIMENSIONS,
            metric_type="COSINE",
            auto_id=False,
        )
        self.load_collection()
        logger.info("milvus collection created name=%s uri=%s", self.collection_name, settings.MILVUS_URI)

    def load_collection(self) -> None:
        if self._loaded:
            return
        self.client.load_collection(collection_name=self.collection_name)
        self._loaded = True

    def delete_document(self, document_id: int) -> None:
        self.ensure_collection()
        try:
            self.client.delete(
                collection_name=self.collection_name,
                filter=f"document_id == {int(document_id)}",
            )
        except Exception as exc:
            logger.warning("milvus delete_document skipped document=%s error=%s", document_id, exc)

    def delete_documents(self, document_ids: Iterable[int]) -> None:
        for document_id in document_ids:
            self.delete_document(int(document_id))

    def index_chunks(self, chunks: Iterable[Chunk]) -> None:
        self.ensure_collection()
        rows = []
        for chunk in chunks:
            if not chunk.embedding:
                continue
            rows.append(
                {
                    "id": int(chunk.id),
                    "vector": chunk.embedding,
                    "chunk_id": int(chunk.id),
                    "kb_id": int(chunk.kb_id),
                    "organization_id": int(chunk.kb.organization_id),
                    "access_policy_id": int(chunk.access_policy_id),
                    "document_id": int(chunk.document_id),
                }
            )
        if not rows:
            return
        self.client.upsert(collection_name=self.collection_name, data=rows)
        logger.info("milvus indexed chunks=%s collection=%s", len(rows), self.collection_name)

    def search(self, kb: KnowledgeBase, query_embedding: list[float], top_k: int, scope) -> list[dict]:
        self.ensure_collection()
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query_embedding],
            limit=top_k,
            filter=scope.milvus_filter_expression(kb.id),
            output_fields=["chunk_id", "kb_id", "document_id", "organization_id", "access_policy_id"],
        )
        hits = []
        for rank, hit in enumerate(results[0] if results else [], start=1):
            entity = hit.get("entity") or {}
            hits.append(
                {
                    "rank": rank,
                    "chunk_id": int(entity.get("chunk_id") or hit.get("id")),
                    "score": float(hit.get("distance", 0)),
                    "engine": "milvus_vector",
                }
            )
        return hits


_store: MilvusVectorStore | None = None


def get_vector_store() -> MilvusVectorStore:
    global _store
    if _store is None:
        _store = MilvusVectorStore()
    return _store
