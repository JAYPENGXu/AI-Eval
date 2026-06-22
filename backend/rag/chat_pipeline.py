from __future__ import annotations

import json
import logging
import time
from typing import Iterator

from django.conf import settings
from django.utils import timezone

from .access_control import audit_access, build_access_scope
from .bm25 import bm25_search
from .config_versions import resolve_runtime_config
from .index_lifecycle import index_health
from .compression import compress_context
from .hybrid import rrf_fusion
from .indexing import get_openai_client
from .model_usage import elapsed_ms, extract_usage, record_model_call
from .models import ChatMessage, ChatSession, Chunk, ModelCallLog, RagTrace
from .query_rewrite import rewrite_query
from .query_router import blocked_route_answer, classify_query_route
from .redaction import redact_sensitive_text, sanitize_trace_results
from .rerank import rerank_candidates
from .retrieval import retrieve
from .session_memory import (
    conversation_context_text,
    get_session_summary_text,
    maybe_schedule_session_summary_update,
    recent_conversation_context,
    rewrite_conversational_question,
    session_summary_metadata,
)

logger = logging.getLogger(__name__)


def source_location_suffix(source: dict) -> str:
    label = str((source.get("location") or {}).get("label") or "").strip()
    return f"，{label}" if label else ""


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
    scope = build_access_scope(session.owner, kb=session.kb)
    if not scope.can_knowledge_base(session.kb, "query"):
        audit_access(scope, "query", session.kb, False, "knowledge_base_denied")
        raise PermissionError("Knowledge base access denied.")
    audit_access(scope, "query", session.kb, True, "rag_pipeline_started")
    raw_options = rag_options or {}
    resolved_options, config_meta = resolve_runtime_config(
        session.kb, raw_options, override_enabled=bool(raw_options.get("override_enabled"))
    )
    rag_options = build_rag_options(resolved_options)
    index_states = [index_health(document) for document in scope.filter_documents(session.kb.documents.all())]
    index_warnings = [reason for state in index_states for reason in state["reasons"]]
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
            organization=session.kb.organization,
            access_scope_fingerprint=scope.fingerprint,
            access_policy_ids=[session.kb.access_policy_id] if session.kb.access_policy_id else [],
            authorization_decision={"allowed": True, "filtered_count": 0},
            redaction_metadata={"prompt_persisted": False},
            question=question,
            rewritten_query=retrieval_query,
            query_intent=route_decision.query_intent,
            route_decision=route_decision.route_decision,
            route_reason=route_decision.route_reason,
            retrieval_mode=route_decision.route_decision,
            final_prompt="",
            settings={
                **route_payload,
                "query_router": route_payload,
                **config_meta,
                "index_health": index_states,
                "index_warnings": index_warnings,
                "query_rewrite_strategy": rewrite_result["rewrite_strategy"],
                "conversation_rewrite_strategy": conversation_rewrite["conversation_rewrite_strategy"],
                "conversation_context_message_count": len(conversation_context or []),
                "session_summary_chars": len(session_summary or ""),
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
    if any(state["critical"] for state in index_states):
        raise RuntimeError("知识库索引的 Embedding 维度与当前配置不兼容，请先重建索引。")
    compression_strategy = rag_options.get("compression_strategy")
    compression_enabled = rag_options.get("compression_enabled")
    try:
        vector_results = retrieve(session.kb, retrieval_query, top_k=rag_options["top_k"], context={"session": session}, scope=scope)
    except Exception as exc:
        message = f"向量检索连接失败，无法可靠回答知识库问题。请检查网络/API/Milvus 状态后重试。原始错误：{exc}"
        logger.exception("vector retrieval failed session=%s", session.id)
        raise RuntimeError(message) from exc
    bm25_results = bm25_search(session.kb, retrieval_query, top_k=rag_options["bm25_top_k"], scope=scope)
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
        f"来源：{source['document']}{source_location_suffix(source)}\n内容：{source['content']}" for source in rerank_results
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
        f"[{source['citation_id']}] 来源：{source['document']}{source_location_suffix(source)}\n内容：{source['content']}" for source in sources
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
    source_chunk_ids = [item.get("chunk_id") for item in sources if item.get("chunk_id")]
    used_policy_ids = sorted(set(scope.filter_chunks(Chunk.objects.filter(id__in=source_chunk_ids)).values_list("access_policy_id", flat=True)))
    trace = RagTrace.objects.create(
        session=session,
        organization=session.kb.organization,
        access_scope_fingerprint=scope.fingerprint,
        access_policy_ids=used_policy_ids,
        authorization_decision={"allowed": True, "filtered_count": 0},
        redaction_metadata={"prompt_persisted": False, "retrieval_results_sanitized": True},
        question=question,
        rewritten_query=retrieval_query,
        query_intent=route_decision.query_intent,
        route_decision=route_decision.route_decision,
        route_reason=route_decision.route_reason,
        retrieval_mode="hybrid_rrf_rerank",
        vector_results=sanitize_trace_results(vector_results),
        bm25_results=sanitize_trace_results(bm25_results),
        hybrid_results=sanitize_trace_results(hybrid_results),
        rerank_results=sanitize_trace_results(rerank_results),
        compression_results=sanitize_trace_results(sources),
        compression_stats=compression_stats,
        original_context="",
        compressed_context="",
        final_prompt="",
        settings={
            **route_payload,
            "query_router": route_payload,
            **config_meta,
            "index_health": index_states,
            "index_warnings": index_warnings,
            "vector_store": settings.VECTOR_STORE,
            "milvus_collection": settings.MILVUS_COLLECTION,
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
            "rag_top_k": rag_options["top_k"],
            "query_rewrite_strategy": rewrite_result["rewrite_strategy"],
            "conversation_rewrite_strategy": conversation_rewrite["conversation_rewrite_strategy"],
            "conversation_context_message_count": len(conversation_context or []),
            "session_summary_chars": len(session_summary or ""),
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


def message_source_fields(sources: list[dict], scope) -> dict:
    compact = []
    chunk_ids = []
    policy_ids = []
    for source in sources or []:
        chunk_id = int(source.get("chunk_id")) if source.get("chunk_id") else None
        if chunk_id:
            chunk_ids.append(chunk_id)
        compact.append({key: source.get(key) for key in ("citation_id", "chunk_id", "score", "engine", "location") if source.get(key) is not None})
    if chunk_ids:
        policy_ids = list(scope.filter_chunks().filter(id__in=chunk_ids).values_list("access_policy_id", flat=True))
    return {
        "sources": compact,
        "source_chunk_ids": sorted(set(chunk_ids)),
        "source_policy_ids": sorted(set(policy_ids)),
        "authorization_snapshot": {"organization_id": scope.organization.id, "scope_fingerprint": scope.fingerprint},
    }


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
        "original_context": "",
        "compressed_context": "",
        "final_prompt": "",
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
        **message_source_fields(sources, build_access_scope(session.owner, kb=session.kb)),
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
                **message_source_fields(sources, build_access_scope(session.owner, kb=session.kb)),
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
            **message_source_fields(sources, build_access_scope(session.owner, kb=session.kb)),
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
        **message_source_fields(sources, build_access_scope(session.owner, kb=session.kb)),
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
