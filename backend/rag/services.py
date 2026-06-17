from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from pathlib import Path
from typing import Iterable, Iterator

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone
from llama_index.core import SimpleDirectoryReader
from openai import OpenAI

from .bm25 import bm25_search, tokenize
from .chunkers import ChunkOptions, get_chunker
from .compression import compress_context
from .hybrid import rrf_fusion
from .models import ChatMessage, ChatSession, ChatSessionSummary, Chunk, Document, KnowledgeBase, ModelCallLog, RagTrace
from .model_usage import elapsed_ms, extract_usage, record_model_call
from .query_rewrite import rewrite_query
from .query_router import blocked_route_answer, classify_query_route
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


CONTEXTUAL_REFERENCE_PATTERN = re.compile(
    r"(他|她|它|他们|她们|它们|这个|那个|该|其|上述|前面|刚才|上一轮|上一个|这位|此人|这些|那些)"
)


def get_session_summary_text(session: ChatSession) -> str:
    try:
        summary_state = session.summary_state
    except ChatSessionSummary.DoesNotExist:
        return ""
    summary = compact_text(summary_state.summary, settings.SESSION_SUMMARY_MAX_CHARS)
    return summary


def session_summary_metadata(session: ChatSession, summary: str) -> dict:
    try:
        summary_state = session.summary_state
    except ChatSessionSummary.DoesNotExist:
        return {
            "session_summary_used": False,
            "session_summary_chars": 0,
            "session_summary_message_count": 0,
            "session_summary_status": "missing",
        }
    return {
        "session_summary_used": bool(summary),
        "session_summary_chars": len(summary or ""),
        "session_summary_message_count": summary_state.summary_message_count,
        "session_summary_status": summary_state.status,
        "session_summary_updated_at": summary_state.updated_at.isoformat() if summary_state.updated_at else None,
    }


def summarize_message_text(messages: list[ChatMessage], limit: int = 400) -> str:
    role_label = {"user": "用户", "assistant": "助手"}
    lines = []
    for message in messages:
        lines.append(f"{role_label.get(message.role, message.role)}：{compact_text(message.content, limit)}")
    return "\n".join(lines)


def estimate_text_tokens(text: str) -> int:
    return max(1, len(text or "") // 2)


def build_session_summary_prompt(old_summary: str, messages: list[ChatMessage]) -> str:
    return (
        "你是 RAG 问答系统的会话记忆摘要器。请把旧摘要和新增对话合并成一份可供后续问题改写使用的会话摘要。\n"
        "要求：\n"
        "1. 只保留对后续知识库问答有用的信息，例如人物、部门、编号、文档范围、用户已澄清的指代关系和当前关注主题。\n"
        "2. 不要总结寒暄，不要加入对话中没有出现的信息。\n"
        "3. 使用简洁中文，控制在指定长度内。\n\n"
        f"旧摘要：\n{old_summary or '无'}\n\n"
        f"新增对话：\n{summarize_message_text(messages)}\n\n"
        f"请输出更新后的摘要，最多 {settings.SESSION_SUMMARY_MAX_CHARS} 个中文字符："
    )


def extract_completion_text(message) -> str:
    content = (getattr(message, "content", None) or "").strip()
    if content:
        return content
    reasoning = (getattr(message, "reasoning_content", None) or "").strip()
    return reasoning


def run_session_summary_update(session_id: int) -> None:
    close_old_connections()
    try:
        session = ChatSession.objects.select_related("owner", "kb").get(id=session_id)
        summary_state = ChatSessionSummary.objects.select_related("covered_until_message").get(session=session)
        old_summary = summary_state.summary or ""
        queryset = session.messages.order_by("created_at", "id")
        if summary_state.covered_until_message_id:
            queryset = queryset.filter(id__gt=summary_state.covered_until_message_id)
        new_messages = list(queryset[: settings.SESSION_SUMMARY_NEW_MESSAGES_LIMIT])
        if not new_messages:
            summary_state.status = "idle"
            summary_state.error_message = ""
            summary_state.save(update_fields=["status", "error_message", "updated_at"])
            return

        model = settings.SESSION_SUMMARY_MODEL or settings.LLM_COMPRESSION_MODEL
        client = OpenAI(
            api_key=settings.LLM_COMPRESSION_API_KEY,
            base_url=settings.LLM_COMPRESSION_API_BASE,
            timeout=settings.LLM_COMPRESSION_TIMEOUT,
        )
        prompt = build_session_summary_prompt(old_summary, new_messages)
        started_at = time.perf_counter()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=settings.SESSION_SUMMARY_MAX_OUTPUT_TOKENS,
        )
        summary = compact_text(extract_completion_text(response.choices[0].message), settings.SESSION_SUMMARY_MAX_CHARS)
        if not summary and not old_summary:
            summary_state.status = "failed"
            summary_state.error_message = "摘要模型返回空内容，将在下次达到条件时重试。"
            summary_state.save(update_fields=["status", "error_message", "updated_at"])
            logger.warning("session summary empty response session=%s model=%s", session.id, model)
            return
        covered_message = new_messages[-1]
        message_count = session.messages.count()
        summary_state.summary = summary or old_summary
        summary_state.summary_message_count = message_count
        summary_state.covered_until_message = covered_message
        summary_state.token_estimate = estimate_text_tokens(summary_state.summary)
        summary_state.status = "idle"
        summary_state.error_message = ""
        summary_state.save(
            update_fields=[
                "summary",
                "summary_message_count",
                "covered_until_message",
                "token_estimate",
                "status",
                "error_message",
                "updated_at",
            ]
        )
        record_model_call(
            call_type="summary",
            model=model,
            provider="openai_compatible",
            usage=extract_usage(response),
            latency_ms=elapsed_ms(started_at),
            owner=session.owner,
            kb=session.kb,
            session=session,
            metadata={
                "summary_stage": "session",
                "new_messages": len(new_messages),
                "summary_message_count": message_count,
            },
        )
        logger.info("session summary updated session=%s messages=%s chars=%s", session.id, message_count, len(summary_state.summary))
    except Exception as exc:
        logger.exception("session summary update failed session=%s", session_id)
        try:
            summary_state = ChatSessionSummary.objects.get(session_id=session_id)
            summary_state.status = "failed"
            summary_state.error_message = str(exc)
            summary_state.save(update_fields=["status", "error_message", "updated_at"])
        except Exception:
            logger.exception("session summary failure state update failed session=%s", session_id)
    finally:
        close_old_connections()


def maybe_schedule_session_summary_update(session: ChatSession) -> None:
    if not settings.SESSION_SUMMARY_ENABLED:
        return
    if not settings.LLM_COMPRESSION_API_KEY:
        logger.info("session summary skipped missing api key session=%s", session.id)
        return
    trigger_messages = max(1, settings.SESSION_SUMMARY_TRIGGER_MESSAGES)
    message_count = session.messages.count()
    try:
        with transaction.atomic():
            summary_state, _ = ChatSessionSummary.objects.select_for_update().get_or_create(session=session)
            if summary_state.status == "running":
                return
            needs_retry = summary_state.status == "failed" or not (summary_state.summary or "").strip()
            if not needs_retry and message_count - summary_state.summary_message_count < trigger_messages:
                return
            summary_state.status = "running"
            summary_state.error_message = ""
            summary_state.last_started_at = timezone.now()
            summary_state.save(update_fields=["status", "error_message", "last_started_at", "updated_at"])
    except Exception:
        logger.exception("session summary schedule failed session=%s", session.id)
        return

    thread = threading.Thread(target=run_session_summary_update, args=(session.id,), daemon=True)
    thread.start()
    logger.info("session summary scheduled session=%s message_count=%s", session.id, message_count)


def recent_conversation_context(session: ChatSession, current_question: str, turns: int | None = None) -> list[dict]:
    limit = max(2, (turns or settings.CONVERSATION_CONTEXT_TURNS) * 2 + 1)
    recent_messages = list(session.messages.order_by("-created_at", "-id")[:limit])
    context_messages = []
    skipped_current = False
    for message in recent_messages:
        if not skipped_current and message.role == "user" and message.content.strip() == current_question.strip():
            skipped_current = True
            continue
        context_messages.append({"role": message.role, "content": compact_text(message.content, 240)})
    context_messages.reverse()
    return context_messages[-max(2, (turns or settings.CONVERSATION_CONTEXT_TURNS) * 2):]


def compact_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit] + "..."


def conversation_context_text(messages: list[dict]) -> str:
    role_label = {"user": "用户", "assistant": "助手"}
    return "\n".join(f"{role_label.get(item['role'], item['role'])}：{item['content']}" for item in messages)


def needs_conversational_rewrite(question: str, messages: list[dict], session_summary: str = "") -> bool:
    if not messages and not session_summary:
        return False
    text = question or ""
    if CONTEXTUAL_REFERENCE_PATTERN.search(text):
        return True
    return len(tokenize(text)) <= 4 and len(text.strip()) <= 24


def latest_user_context(messages: list[dict]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user" and item.get("content"):
            return item["content"]
    return ""


def rewrite_conversational_question(question: str, messages: list[dict], session_summary: str = "", context: dict | None = None) -> dict:
    if not needs_conversational_rewrite(question, messages, session_summary):
        return {
            "original_question": question,
            "standalone_question": question,
            "conversation_rewrite_strategy": "none",
            "conversation_context": messages,
        }

    if settings.LLM_COMPRESSION_API_KEY:
        try:
            client = OpenAI(
                api_key=settings.LLM_COMPRESSION_API_KEY,
                base_url=settings.LLM_COMPRESSION_API_BASE,
                timeout=settings.LLM_COMPRESSION_TIMEOUT,
            )
            prompt = (
                "你是 RAG 多轮问答的问题改写器。请根据最近对话，把当前问题改写成一个脱离上下文也能独立检索的完整问题。\n"
                "要求：只输出改写后的问题；不要回答问题；不要编造对话中没有的信息；"
                "如果上下文不足以确定指代，就保留原问题并补充必要限定词。\n\n"
                f"会话摘要：\n{session_summary or '无'}\n\n"
                f"最近对话：\n{conversation_context_text(messages) if messages else '无'}\n\n"
                f"当前问题：{question}\n"
                "独立问题："
            )
            started_at = time.perf_counter()
            response = client.chat.completions.create(
                model=settings.LLM_COMPRESSION_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=128,
            )
            record_model_call(
                call_type="rewrite",
                model=settings.LLM_COMPRESSION_MODEL,
                provider="openai_compatible",
                usage=extract_usage(response),
                latency_ms=elapsed_ms(started_at),
                metadata={"rewrite_stage": "conversation"},
                **(context or {}),
            )
            standalone = (response.choices[0].message.content or "").strip()
            return {
                "original_question": question,
                "standalone_question": standalone or fallback_conversational_rewrite(question, messages, session_summary),
                "conversation_rewrite_strategy": "llm_conversation",
                "conversation_context": messages,
                "session_summary": session_summary,
            }
        except Exception as exc:
            record_model_call(
                call_type="rewrite",
                model=settings.LLM_COMPRESSION_MODEL,
                provider="openai_compatible",
                status="failed",
                error_message=str(exc),
                metadata={"rewrite_stage": "conversation"},
                **(context or {}),
            )
            logger.warning("conversation query rewrite failed fallback=rule error=%s", exc)

    return {
        "original_question": question,
        "standalone_question": fallback_conversational_rewrite(question, messages, session_summary),
        "conversation_rewrite_strategy": "rule_conversation",
        "conversation_context": messages,
        "session_summary": session_summary,
    }


def fallback_conversational_rewrite(question: str, messages: list[dict], session_summary: str = "") -> str:
    if session_summary:
        return f"{compact_text(session_summary, 500)} {question.strip()}".strip()
    previous_user = latest_user_context(messages)
    if previous_user:
        return f"{previous_user.rstrip()} {question.strip()}".strip()
    return question


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
    conversation_context = recent_conversation_context(session, question)
    session_summary = get_session_summary_text(session)
    summary_meta = session_summary_metadata(session, session_summary)
    conversation_rewrite = rewrite_conversational_question(
        question,
        conversation_context,
        session_summary=session_summary,
        context={"owner": session.owner, "kb": session.kb, "session": session},
    )
    standalone_question = conversation_rewrite["standalone_question"]
    route_decision = classify_query_route(question, standalone_question)
    rewrite_result = rewrite_query(
        standalone_question,
        rag_options.get("query_rewrite_strategy"),
        context={"owner": session.owner, "kb": session.kb, "session": session},
    )
    retrieval_query = rewrite_result["rewritten_query"]
    route_payload = route_decision.as_dict()
    if route_decision.query_intent != "internal_knowledge":
        answer = blocked_route_answer(route_decision)
        prompt = (
            "Query Router 拒绝进入内部知识库 RAG 检索。\n"
            f"Intent: {route_decision.query_intent}\n"
            f"Decision: {route_decision.route_decision}\n"
            f"Reason: {route_decision.route_reason}\n"
            f"Original Query: {question}\n"
            f"Standalone Query: {standalone_question}\n"
        )
        trace = RagTrace.objects.create(
            session=session,
            question=question,
            rewritten_query=retrieval_query,
            query_intent=route_decision.query_intent,
            route_decision=route_decision.route_decision,
            route_reason=route_decision.route_reason,
            retrieval_mode=route_decision.route_decision,
            final_prompt=prompt,
            settings={
                **route_payload,
                "query_router": route_payload,
                "query_rewrite_strategy": rewrite_result["rewrite_strategy"],
                "conversation_rewrite_strategy": conversation_rewrite["conversation_rewrite_strategy"],
                "conversation_context": conversation_context,
                "session_summary": session_summary,
                **summary_meta,
                "original_query": question,
                "standalone_query": standalone_question,
                "base_rewrite_original_query": rewrite_result["original_query"],
                "rewritten_query": rewrite_result["rewritten_query"],
                "request_options": rag_options,
                "blocked_answer": answer,
            },
        )
        return prompt, [], trace
    compression_strategy = rag_options.get("compression_strategy")
    compression_enabled = rag_options.get("compression_enabled")
    try:
        vector_results = retrieve(session.kb, retrieval_query, top_k=rag_options["top_k"], context={"session": session})
    except Exception as exc:
        message = f"向量检索连接失败，无法可靠回答知识库问题。请检查网络/API/Milvus 状态后重试。原始错误：{exc}"
        logger.exception("vector retrieval failed session=%s", session.id)
        raise RuntimeError(message) from exc
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
    conversation_block = ""
    if session_summary:
        conversation_block += f"会话摘要：\n{session_summary}\n\n"
    if conversation_context:
        conversation_block += f"最近对话上下文：\n{conversation_context_text(conversation_context)}\n\n"
    prompt = (
        "你是一个严谨的知识库问答助手。"
        "请严格依据参考资料回答用户问题。\n"
        "每个事实性结论后都要标注引用编号，例如 [1] 或 [1][2]。\n"
        "引用编号必须来自参考资料编号，不要编造不存在的编号。\n"
        "如果多个来源共同支持一个结论，可以连续标注多个编号。\n"
        "如果用户问题包含代词或省略，请结合最近对话上下文理解指代；"
        "如果仍无法唯一确定对象，请先说明需要澄清。\n"
        "如果参考资料不足以回答，"
        '请明确说明"当前知识库资料不足以回答"。\n\n'
        f"{conversation_block}"
        f"参考资料：\n{compressed_context}\n\n"
        f"用户原始问题：{question}\n"
        f"用于检索的独立问题：{standalone_question}\n\n回答："
    )
    trace = RagTrace.objects.create(
        session=session,
        question=question,
        rewritten_query=retrieval_query,
        query_intent=route_decision.query_intent,
        route_decision=route_decision.route_decision,
        route_reason=route_decision.route_reason,
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
            **route_payload,
            "query_router": route_payload,
            "vector_store": settings.VECTOR_STORE,
            "milvus_collection": settings.MILVUS_COLLECTION,
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
            "rag_top_k": rag_options["top_k"],
            "query_rewrite_strategy": rewrite_result["rewrite_strategy"],
            "conversation_rewrite_strategy": conversation_rewrite["conversation_rewrite_strategy"],
            "conversation_context": conversation_context,
            "session_summary": session_summary,
            **summary_meta,
            "original_query": question,
            "standalone_query": standalone_question,
            "base_rewrite_original_query": rewrite_result["original_query"],
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
        "query_intent": trace.query_intent,
        "route_decision": trace.route_decision,
        "route_reason": trace.route_reason,
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
    if trace.query_intent != "internal_knowledge":
        answer = trace.settings.get("blocked_answer") or blocked_route_answer(
            classify_query_route(trace.question, trace.rewritten_query)
        )
        message = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content=answer,
            sources=[],
        )
        trace.message = message
        trace.save(update_fields=["message"])
        session.save(update_fields=["updated_at"])
        maybe_schedule_session_summary_update(session)
        return message
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
    session.save(update_fields=["updated_at"])
    maybe_schedule_session_summary_update(session)
    return message


def stream_answer_events(session: ChatSession, question: str, rag_options: dict | None = None) -> Iterator[dict]:
    logger.info("rag stream start session=%s question_len=%s", session.id, len(question))
    prompt, sources, trace = build_rag_prompt(session, question, rag_options)
    logger.info("rag stream sources session=%s count=%s", session.id, len(sources))
    yield {"event": "sources", "data": sources}
    yield {"event": "trace", "data": serialize_trace(trace)}
    if trace.query_intent != "internal_knowledge":
        answer = trace.settings.get("blocked_answer") or blocked_route_answer(
            classify_query_route(trace.question, trace.rewritten_query)
        )
        message = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content=answer,
            sources=[],
        )
        trace.message = message
        trace.save(update_fields=["message"])
        session.save(update_fields=["updated_at"])
        maybe_schedule_session_summary_update(session)
        yield {"event": "delta", "data": {"content": answer}}
        yield {"event": "done", "data": serialize_message(message)}
        return

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
        if delta_count > 0:
            raise

        logger.warning("rag stream failed before first delta; falling back to non-stream chat session=%s error=%s", session.id, exc)
        fallback_started_at = time.perf_counter()
        try:
            fallback_completion = client.chat.completions.create(
                model=settings.CHAT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )
        except Exception as fallback_exc:
            record_model_call(
                call_type="chat",
                model=settings.CHAT_MODEL,
                provider="openai_compatible",
                status="failed",
                latency_ms=elapsed_ms(fallback_started_at),
                error_message=str(fallback_exc),
                session=session,
                trace=trace,
                metadata={"stream": False, "fallback_after_stream_error": True},
            )
            fallback_answer = (
                "模型服务当前连接失败，暂时无法生成最终回答。"
                "系统已完成可用的检索步骤并保存 Trace；请稍后重试，"
                "或检查 WSL 到模型服务 API 的网络连通性。"
            )
            message = ChatMessage.objects.create(
                session=session,
                role="assistant",
                content=fallback_answer,
                sources=json.loads(json.dumps(sources)),
            )
            trace.message = message
            trace.settings = {
                **(trace.settings or {}),
                "answer_generation_error": str(fallback_exc),
                "answer_generation_fallback": "model_connection_failed_message",
            }
            trace.save(update_fields=["message", "settings"])
            session.save(update_fields=["updated_at"])
            maybe_schedule_session_summary_update(session)
            yield {"event": "delta", "data": {"content": fallback_answer}}
            yield {"event": "done", "data": serialize_message(message)}
            return

        fallback_answer = fallback_completion.choices[0].message.content or ""
        message = ChatMessage.objects.create(
            session=session,
            role="assistant",
            content=fallback_answer,
            sources=json.loads(json.dumps(sources)),
        )
        record_model_call(
            call_type="chat",
            model=settings.CHAT_MODEL,
            provider="openai_compatible",
            usage=extract_usage(fallback_completion),
            latency_ms=elapsed_ms(fallback_started_at),
            session=session,
            message=message,
            trace=trace,
            metadata={"stream": False, "fallback_after_stream_error": True},
        )
        trace.message = message
        trace.save(update_fields=["message"])
        session.save(update_fields=["updated_at"])
        maybe_schedule_session_summary_update(session)
        yield {"event": "delta", "data": {"content": fallback_answer}}
        yield {"event": "done", "data": serialize_message(message)}
        return

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
    maybe_schedule_session_summary_update(session)
    logger.info("rag stream done session=%s chunks=%s chars=%s", session.id, delta_count, len(message.content))
    yield {"event": "done", "data": serialize_message(message)}
