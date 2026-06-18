from __future__ import annotations

import logging
import time
from pathlib import Path

from django.conf import settings
from llama_index.core import SimpleDirectoryReader
from openai import OpenAI

from .chunkers import ChunkOptions, get_chunker
from .models import ChatSession, Chunk, Document, KnowledgeBase, RagTrace
from .model_usage import elapsed_ms, extract_usage, record_model_call
from .vector_store import get_vector_store

logger = logging.getLogger(__name__)


def read_document_text(document: Document) -> str:
    path = Path(document.file.path)
    docs = SimpleDirectoryReader(input_files=[str(path)]).load_data()
    return "\n\n".join(item.text for item in docs if item.text).strip()


def build_options(data: dict | None) -> ChunkOptions:
    data = data or {}
    return ChunkOptions(
        chunk_size=int(data.get("chunk_size") or 800),
        chunk_overlap=int(data.get("chunk_overlap") or 100),
        window_size=int(data.get("window_size") or 1),
        semantic_threshold=float(data.get("semantic_threshold") or 0.72),
    )


def preview_chunks(document: Document, method: str, options_data: dict | None) -> list[dict]:
    text = read_document_text(document)
    chunker = get_chunker(method)
    chunks = chunker.split(text, build_options(options_data))
    return [
        {
            "index": chunk.index,
            "content": chunk.content,
            "token_count": chunk.token_count,
            "metadata": chunk.metadata,
        }
        for chunk in chunks
    ]


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=settings.API_KEY, base_url=settings.API_BASE)


def embed_texts(
    texts: list[str],
    *,
    call_type: str = "embedding_query",
    owner=None,
    kb: KnowledgeBase | None = None,
    session: ChatSession | None = None,
    trace: RagTrace | None = None,
    metadata: dict | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    client = get_openai_client()
    embeddings = []
    batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        started_at = time.perf_counter()
        try:
            response = client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=batch,
                dimensions=settings.EMBEDDING_DIMENSIONS,
            )
        except Exception as exc:
            record_model_call(
                call_type=call_type,
                model=settings.EMBEDDING_MODEL,
                provider="openai_compatible",
                status="failed",
                latency_ms=elapsed_ms(started_at),
                error_message=str(exc),
                owner=owner,
                kb=kb,
                session=session,
                trace=trace,
                metadata={**(metadata or {}), "batch_size": len(batch), "batch_start": start},
            )
            raise
        record_model_call(
            call_type=call_type,
            model=settings.EMBEDDING_MODEL,
            provider="openai_compatible",
            usage=extract_usage(response),
            latency_ms=elapsed_ms(started_at),
            owner=owner,
            kb=kb,
            session=session,
            trace=trace,
            metadata={**(metadata or {}), "batch_size": len(batch), "batch_start": start},
        )
        embeddings.extend(item.embedding for item in response.data)
    return embeddings


def index_document(document: Document, method: str, options_data: dict | None) -> int:
    chunks = preview_chunks(document, method, options_data)
    get_vector_store().delete_document(document.id)
    document.chunks.all().delete()
    texts = [chunk["content"] for chunk in chunks]
    try:
        embeddings = embed_texts(
            texts,
            call_type="embedding_index",
            owner=document.kb.owner,
            kb=document.kb,
            metadata={"document_id": document.id},
        )
    except Exception as exc:
        message = f"Embedding 服务连接失败，文档未完成索引。请检查网络/API 配置后重试。原始错误：{exc}"
        document.status = "failed"
        document.error_message = message
        document.save(update_fields=["status", "error_message", "updated_at"])
        logger.exception("document embedding failed document=%s", document.id)
        raise RuntimeError(message) from exc

    created_chunks = []
    for chunk, embedding in zip(chunks, embeddings):
        created_chunks.append(
            Chunk.objects.create(
                document=document,
                kb=document.kb,
                index=chunk["index"],
                content=chunk["content"],
                token_count=chunk["token_count"],
                metadata=chunk["metadata"],
                embedding=embedding,
            )
        )
    try:
        get_vector_store().index_chunks(created_chunks)
    except Exception as exc:
        message = f"向量索引写入失败，文档未完成索引。请检查 Milvus/Vector Store 状态后重试。原始错误：{exc}"
        document.status = "failed"
        document.error_message = message
        document.save(update_fields=["status", "error_message", "updated_at"])
        logger.exception("document vector indexing failed document=%s", document.id)
        raise RuntimeError(message) from exc

    document.chunk_method = method
    document.chunk_options = options_data or {}
    document.status = "indexed"
    document.error_message = ""
    document.save(update_fields=["chunk_method", "chunk_options", "status", "error_message", "updated_at"])
    return len(chunks)
