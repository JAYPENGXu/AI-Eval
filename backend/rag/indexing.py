from __future__ import annotations

import logging
import time

from django.conf import settings
from openai import OpenAI

from .chunkers import ChunkOptions, get_chunker
from .document_parsing.ir import load_document_ir
from .models import ChatSession, Chunk, Document, DocumentParseRun, KnowledgeBase, RagTrace
from .model_usage import elapsed_ms, extract_usage, record_model_call
from .vector_store import get_vector_store

logger = logging.getLogger(__name__)


class ParseRunNotReadyError(ValueError):
    pass


def resolve_parse_run(document: Document, parse_run_id: int | None = None) -> DocumentParseRun:
    queryset = document.parse_runs.filter(status="completed")
    if parse_run_id:
        queryset = queryset.filter(id=parse_run_id)
    run = queryset.order_by("-created_at", "-id").first()
    if not run:
        raise ParseRunNotReadyError("文档解析尚未完成，或解析结果仍待人工确认。")
    return run


def read_document_text(document: Document, parse_run_id: int | None = None) -> str:
    return load_document_ir(resolve_parse_run(document, parse_run_id)).text


def build_options(data: dict | None) -> ChunkOptions:
    data = data or {}
    return ChunkOptions(
        chunk_size=int(data.get("chunk_size") or 800),
        chunk_overlap=int(data.get("chunk_overlap") or 100),
        window_size=int(data.get("window_size") or 1),
        semantic_threshold=float(data.get("semantic_threshold") or 0.72),
    )


def preview_chunks(
    document: Document,
    method: str,
    options_data: dict | None,
    parse_run_id: int | None = None,
) -> list[dict]:
    parse_run = resolve_parse_run(document, parse_run_id)
    document_ir = load_document_ir(parse_run)
    chunks = get_chunker(method).split(document_ir, build_options(options_data))
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


def index_document(
    document: Document,
    method: str,
    options_data: dict | None,
    parse_run_id: int | None = None,
) -> int:
    parse_run = resolve_parse_run(document, parse_run_id)
    chunks = preview_chunks(document, method, options_data, parse_run.id)
    if not chunks:
        raise ValueError("解析结果没有可索引内容。")
    old_chunks = list(document.chunks.all())
    document.status = "indexing"
    document.error_message = ""
    document.save(update_fields=["status", "error_message", "updated_at"])
    texts = [chunk["content"] for chunk in chunks]
    try:
        embeddings = embed_texts(
            texts,
            call_type="embedding_index",
            owner=document.kb.owner,
            kb=document.kb,
            metadata={"document_id": document.id, "parse_run_id": parse_run.id},
        )
    except Exception as exc:
        message = f"Embedding 服务连接失败，旧索引保持可用。请检查网络/API 配置后重试。原始错误：{exc}"
        document.status = "failed"
        document.error_message = message
        document.save(update_fields=["status", "error_message", "updated_at"])
        logger.exception("document embedding failed document=%s", document.id)
        raise RuntimeError(message) from exc

    if len(embeddings) != len(chunks):
        raise RuntimeError(f"Embedding 返回数量异常：期望 {len(chunks)}，实际 {len(embeddings)}。")

    created_chunks = [
        Chunk.objects.create(
            document=document,
            kb=document.kb,
            parse_run=parse_run,
            access_policy=document.access_policy,
            inherits_policy=True,
            index=chunk["index"],
            content=chunk["content"],
            token_count=chunk["token_count"],
            metadata=chunk["metadata"],
            embedding=embedding,
        )
        for chunk, embedding in zip(chunks, embeddings)
    ]
    store = get_vector_store()
    try:
        store.delete_document(document.id)
        store.index_chunks(created_chunks)
    except Exception as exc:
        Chunk.objects.filter(id__in=[chunk.id for chunk in created_chunks]).delete()
        try:
            store.delete_document(document.id)
            store.index_chunks(old_chunks)
        except Exception:
            logger.exception("failed to restore previous vector index document=%s", document.id)
        message = f"向量索引写入失败，数据库中的旧索引保持可用。请检查 Milvus 状态后重试。原始错误：{exc}"
        document.status = "failed"
        document.error_message = message
        document.save(update_fields=["status", "error_message", "updated_at"])
        logger.exception("document vector indexing failed document=%s", document.id)
        raise RuntimeError(message) from exc

    if old_chunks:
        Chunk.objects.filter(id__in=[chunk.id for chunk in old_chunks]).delete()
    document.chunk_method = method
    document.chunk_options = options_data or {}
    document.status = "indexed"
    document.error_message = ""
    document.save(update_fields=["chunk_method", "chunk_options", "status", "error_message", "updated_at"])
    return len(chunks)
