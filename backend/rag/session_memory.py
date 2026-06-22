from __future__ import annotations

import logging
import re
import time

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone
from openai import OpenAI

from .bm25 import tokenize
from .model_usage import elapsed_ms, extract_usage, record_model_call
from .models import ChatMessage, ChatSession, ChatSessionSummary

logger = logging.getLogger(__name__)

CONTEXTUAL_REFERENCE_PATTERN = re.compile(
    r"(他|她|它|他们|她们|它们|这个|那个|该|其|上述|前面|刚才|上一轮|上一个|这位|此人|这些|那些)"
)


def compact_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit] + "..."


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
            if summary_state.status in {"queued", "running"}:
                return
            needs_retry = summary_state.status == "failed" or not (summary_state.summary or "").strip()
            if not needs_retry and message_count - summary_state.summary_message_count < trigger_messages:
                return
            summary_state.status = "queued"
            summary_state.error_message = ""
            summary_state.last_started_at = timezone.now()
            summary_state.save(update_fields=["status", "error_message", "last_started_at", "updated_at"])
    except Exception:
        logger.exception("session summary schedule failed session=%s", session.id)
        return

    from .tasks import session_summary_task
    try:
        result = session_summary_task.apply_async(args=[session.id], queue="summaries")
        ChatSessionSummary.objects.filter(session=session, status="queued").update(celery_task_id=result.id)
        logger.info("session summary queued session=%s message_count=%s", session.id, message_count)
    except Exception as exc:
        ChatSessionSummary.objects.filter(session=session).update(status="failed", error_message=f"摘要任务入队失败：{exc}")
        logger.exception("session summary enqueue failed session=%s", session.id)


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


def fallback_conversational_rewrite(question: str, messages: list[dict], session_summary: str = "") -> str:
    if session_summary:
        return f"{compact_text(session_summary, 500)} {question.strip()}".strip()
    previous_user = latest_user_context(messages)
    if previous_user:
        return f"{previous_user.rstrip()} {question.strip()}".strip()
    return question


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
