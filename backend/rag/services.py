from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Iterable, Iterator

from django.conf import settings
from django.utils import timezone
from llama_index.core import SimpleDirectoryReader
from openai import OpenAI

from .bm25 import bm25_search
from .chunkers import ChunkOptions, get_chunker
from .compression import compress_context
from .hybrid import rrf_fusion
from .models import ChatMessage, ChatSession, Chunk, Document, KnowledgeBase, ModelCallLog, RagTrace
from .model_usage import elapsed_ms, extract_usage, record_model_call
from .query_rewrite import rewrite_query
from .rerank import rerank_candidates
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


def index_document(document: Document, method: str, options_data: dict | None) -> int:
    chunks = preview_chunks(document, method, options_data)
    get_vector_store().delete_document(document.id)
    document.chunks.all().delete()
    texts = [chunk["content"] for chunk in chunks]
    embeddings = embed_texts(texts, call_type="embedding_index", owner=document.kb.owner, kb=document.kb, metadata={"document_id": document.id})
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
    get_vector_store().index_chunks(created_chunks)
    document.chunk_method = method
    document.chunk_options = options_data or {}
    document.status = "indexed"
    document.error_message = ""
    document.save(update_fields=["chunk_method", "chunk_options", "status", "error_message", "updated_at"])
    return len(chunks)


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


def cosine(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = list(left)
    right_values = list(right)
    dot = sum(a * b for a, b in zip(left_values, right_values))
    left_norm = math.sqrt(sum(a * a for a in left_values))
    right_norm = math.sqrt(sum(b * b for b in right_values))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0


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


def retrieve_with_sqlite(kb: KnowledgeBase, query_embedding: list[float], top_k: int) -> list[dict]:
    scored = []
    for chunk in Chunk.objects.filter(kb=kb).exclude(embedding__isnull=True).select_related("document"):
        scored.append((cosine(query_embedding, chunk.embedding), chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        format_source(chunk, score, rank, "sqlite_vector_fallback")
        for rank, (score, chunk) in enumerate(scored[:top_k], start=1)
    ]


def format_source(chunk: Chunk, score: float, rank: int, engine: str) -> dict:
    return {
        "rank": rank,
        "chunk_id": chunk.id,
        "document": chunk.document.filename,
        "score": score,
        "engine": engine,
        "content": chunk.content,
        "metadata": chunk.metadata,
    }


def int_option(options: dict, name: str, default: int, *, minimum: int = 1, maximum: int = 50) -> int:
    try:
        value = int(options.get(name, default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def build_rag_options(raw_options: dict | None) -> dict:
    raw_options = raw_options or {}
    vector_top_k = int_option(raw_options, "top_k", settings.RAG_TOP_K, maximum=20)
    bm25_top_k = int_option(raw_options, "bm25_top_k", settings.BM25_TOP_K, maximum=20)
    rerank_top_n = int_option(raw_options, "rerank_top_n", settings.RERANK_TOP_N, maximum=20)
    hybrid_top_k = int_option(
        raw_options,
        "hybrid_top_k",
        max(settings.HYBRID_TOP_K, vector_top_k, bm25_top_k, rerank_top_n),
        maximum=30,
    )
    hybrid_top_k = max(hybrid_top_k, rerank_top_n)
    return {
        "top_k": vector_top_k,
        "bm25_top_k": bm25_top_k,
        "hybrid_top_k": hybrid_top_k,
        "rrf_k": int_option(raw_options, "rrf_k", settings.RRF_K, minimum=1, maximum=500),
        "rerank_top_n": rerank_top_n,
        "rerank_candidate_n": int_option(raw_options, "rerank_candidate_n", hybrid_top_k, maximum=30),
        "query_rewrite_strategy": raw_options.get("query_rewrite_strategy"),
        "compression_strategy": raw_options.get("compression_strategy"),
        "compression_enabled": raw_options.get("compression_enabled"),
    }


def build_rag_prompt(session: ChatSession, question: str, rag_options: dict | None = None) -> tuple[str, list[dict], RagTrace]:
    pipeline_started_at = timezone.now()
    rag_options = build_rag_options(rag_options)
    rewrite_result = rewrite_query(question, rag_options.get("query_rewrite_strategy"), context={"owner": session.owner, "kb": session.kb, "session": session})
    retrieval_query = rewrite_result["rewritten_query"]
    compression_strategy = rag_options.get("compression_strategy")
    compression_enabled = rag_options.get("compression_enabled")
    vector_results = retrieve(session.kb, retrieval_query, top_k=rag_options["top_k"], context={"session": session})
    bm25_results = bm25_search(session.kb, retrieval_query, top_k=rag_options["bm25_top_k"])
    hybrid_results = rrf_fusion(
        bm25_results,
        vector_results,
        top_k=rag_options["hybrid_top_k"],
        rrf_k=rag_options["rrf_k"],
    )
    rerank_results = rerank_candidates(
        retrieval_query,
        hybrid_results,
        top_n=rag_options["rerank_top_n"],
        candidate_n=rag_options["rerank_candidate_n"],
        context={"owner": session.owner, "kb": session.kb, "session": session},
    )
    original_context = "\n\n---\n\n".join(
        f"\u6765\u6e90\uff1a{source['document']}\n\u5185\u5bb9\uff1a{source['content']}" for source in rerank_results
    )
    sources, compression_stats = compress_context(
        retrieval_query,
        rerank_results,
        strategy=compression_strategy,
        enabled=compression_enabled,
        context={"owner": session.owner, "kb": session.kb, "session": session},
    )
    for citation_id, source in enumerate(sources, start=1):
        source["citation_id"] = citation_id

    compressed_context = "\n\n---\n\n".join(
        f"[{source['citation_id']}] 来源：{source['document']}\n内容：{source['content']}" for source in sources
    )
    prompt = (
        "你是一个严谨的知识库问答助手。"
        "请严格依据参考资料回答用户问题。\n"
        "每个事实性结论后都要标注引用编号，例如 [1] 或 [1][2]。\n"
        "引用编号必须来自参考资料编号，不要编造不存在的编号。\n"
        "如果多个来源共同支持一个结论，可以连续标注多个编号。\n"
        "如果参考资料不足以回答，"
        '请明确说明"当前知识库资料不足以回答"。\n\n'
        f"参考资料：\n{compressed_context}\n\n"
        f"用户问题：{question}\n\n回答："
    )
    trace = RagTrace.objects.create(
        session=session,
        question=question,
        rewritten_query=retrieval_query,
        retrieval_mode="hybrid_rrf_rerank",
        vector_results=vector_results,
        bm25_results=bm25_results,
        hybrid_results=hybrid_results,
        rerank_results=rerank_results,
        compression_results=sources,
        compression_stats=compression_stats,
        original_context=original_context,
        compressed_context=compressed_context,
        final_prompt=prompt,
        settings={
            "vector_store": settings.VECTOR_STORE,
            "milvus_collection": settings.MILVUS_COLLECTION,
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
            "rag_top_k": rag_options["top_k"],
            "query_rewrite_strategy": rewrite_result["rewrite_strategy"],
            "original_query": rewrite_result["original_query"],
            "rewritten_query": rewrite_result["rewritten_query"],
            "bm25_top_k": rag_options["bm25_top_k"],
            "bm25_k1": settings.BM25_K1,
            "bm25_b": settings.BM25_B,
            "hybrid_top_k": rag_options["hybrid_top_k"],
            "rrf_k": rag_options["rrf_k"],
            "rerank_enabled": settings.RERANK_ENABLED,
            "rerank_model": settings.RERANK_MODEL,
            "rerank_top_n": rag_options["rerank_top_n"],
            "rerank_candidate_n": rag_options["rerank_candidate_n"],
            "context_compression_enabled": compression_stats["strategy"] != "none",
            "context_compression_strategy": compression_stats["strategy"],
            "compression_max_sentences_per_chunk": settings.COMPRESSION_MAX_SENTENCES_PER_CHUNK,
            "compression_sentence_window": settings.COMPRESSION_SENTENCE_WINDOW,
            "compression_list_item_window": settings.COMPRESSION_LIST_ITEM_WINDOW,
            "compression_min_score": settings.COMPRESSION_MIN_SCORE,
            "llm_compression_model": settings.LLM_COMPRESSION_MODEL,
            "llm_compression_api_base": settings.LLM_COMPRESSION_API_BASE,
            "request_options": rag_options,
        },
    )
    ModelCallLog.objects.filter(
        owner=session.owner,
        kb=session.kb,
        session=session,
        trace__isnull=True,
        created_at__gte=pipeline_started_at,
    ).update(trace=trace)
    return prompt, sources, trace


def serialize_message(message: ChatMessage) -> dict:
    data = {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "sources": message.sources,
        "created_at": message.created_at.isoformat(),
    }
    trace = getattr(message, "trace", None)
    if trace:
        data["trace"] = serialize_trace(trace)
    return data


def serialize_trace(trace: RagTrace) -> dict:
    return {
        "id": trace.id,
        "question": trace.question,
        "rewritten_query": trace.rewritten_query,
        "retrieval_mode": trace.retrieval_mode,
        "vector_results": trace.vector_results,
        "bm25_results": trace.bm25_results,
        "hybrid_results": trace.hybrid_results,
        "rerank_results": trace.rerank_results,
        "compression_results": trace.compression_results,
        "compression_stats": trace.compression_stats,
        "original_context": trace.original_context,
        "compressed_context": trace.compressed_context,
        "final_prompt": trace.final_prompt,
        "settings": trace.settings,
        "created_at": trace.created_at.isoformat(),
    }


def answer_question(session: ChatSession, question: str, rag_options: dict | None = None) -> ChatMessage:
    prompt, sources, trace = build_rag_prompt(session, question, rag_options)
    client = get_openai_client()
    started_at = time.perf_counter()
    try:
        completion = client.chat.completions.create(
            model=settings.CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        record_model_call(
            call_type="chat",
            model=settings.CHAT_MODEL,
            provider="openai_compatible",
            status="failed",
            latency_ms=elapsed_ms(started_at),
            error_message=str(exc),
            session=session,
            trace=trace,
            metadata={"stream": False},
        )
        raise
    answer = completion.choices[0].message.content or ""
    message = ChatMessage.objects.create(
        session=session,
        role="assistant",
        content=answer,
        sources=json.loads(json.dumps(sources)),
    )
    record_model_call(
        call_type="chat",
        model=settings.CHAT_MODEL,
        provider="openai_compatible",
        usage=extract_usage(completion),
        latency_ms=elapsed_ms(started_at),
        session=session,
        message=message,
        trace=trace,
        metadata={"stream": False},
    )
    trace.message = message
    trace.save(update_fields=["message"])
    return message


def stream_answer_events(session: ChatSession, question: str, rag_options: dict | None = None) -> Iterator[dict]:
    logger.info("rag stream start session=%s question_len=%s", session.id, len(question))
    prompt, sources, trace = build_rag_prompt(session, question, rag_options)
    logger.info("rag stream sources session=%s count=%s", session.id, len(sources))
    yield {"event": "sources", "data": sources}
    yield {"event": "trace", "data": serialize_trace(trace)}

    client = get_openai_client()
    started_at = time.perf_counter()
    usage_data = None
    answer_parts = []
    delta_count = 0
    try:
        stream_kwargs = {
            "model": settings.CHAT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        if settings.CHAT_STREAM_INCLUDE_USAGE:
            stream_kwargs["stream_options"] = {"include_usage": True}
        completion = client.chat.completions.create(**stream_kwargs)

        for chunk in completion:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage:
                usage_data = extract_usage(chunk)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = choices[0].delta.content or ""
            if not delta:
                continue
            delta_count += 1
            if delta_count == 1:
                logger.info("rag stream first_delta session=%s", session.id)
            elif delta_count % 20 == 0:
                logger.info("rag stream delta_progress session=%s chunks=%s chars=%s", session.id, delta_count, sum(len(part) for part in answer_parts))
            answer_parts.append(delta)
            yield {"event": "delta", "data": {"content": delta}}
    except Exception as exc:
        record_model_call(
            call_type="chat",
            model=settings.CHAT_MODEL,
            provider="openai_compatible",
            status="failed",
            latency_ms=elapsed_ms(started_at),
            error_message=str(exc),
            session=session,
            trace=trace,
            metadata={"stream": True, "delta_count": delta_count},
        )
        raise

    message = ChatMessage.objects.create(
        session=session,
        role="assistant",
        content="".join(answer_parts),
        sources=json.loads(json.dumps(sources)),
    )
    record_model_call(
        call_type="chat",
        model=settings.CHAT_MODEL,
        provider="openai_compatible",
        usage=usage_data,
        latency_ms=elapsed_ms(started_at),
        session=session,
        message=message,
        trace=trace,
        metadata={"stream": True, "delta_count": delta_count},
    )
    trace.message = message
    trace.save(update_fields=["message"])
    session.save(update_fields=["updated_at"])
    logger.info("rag stream done session=%s chunks=%s chars=%s", session.id, delta_count, len(message.content))
    yield {"event": "done", "data": serialize_message(message)}
