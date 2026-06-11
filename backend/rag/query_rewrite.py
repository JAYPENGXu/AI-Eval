from __future__ import annotations

import logging
import re
import time

from django.conf import settings
from openai import OpenAI

from .bm25 import tokenize
from .model_usage import elapsed_ms, extract_usage, record_model_call


logger = logging.getLogger(__name__)

DISABLED_STRATEGIES = {"none", "disabled", "off", "no_rewrite"}
ENABLED_STRATEGIES = {"rule", "llm"}
DEFAULT_STRATEGY = "rule"

STAGE_PATTERN = re.compile(r"([\u4e00-\u9fffA-Za-z0-9_]+?)\u9636\u6bb5")
TARGET_HINTS = [
    ("工具", "使用工具"),
    ("注意", "注意事项"),
    ("指导", "操作指导"),
    ("操作", "操作指导"),
]


def rewrite_query(question: str, strategy: str | None = None, context: dict | None = None) -> dict:
    selected_strategy = normalize_strategy(strategy)
    if selected_strategy == "none":
        return build_result(question, question, selected_strategy)
    if selected_strategy == "llm":
        return rewrite_with_llm(question, context=context)
    return build_result(question, rule_rewrite(question), selected_strategy)


def normalize_strategy(strategy: str | None) -> str:
    value = (strategy or getattr(settings, "QUERY_REWRITE_STRATEGY", DEFAULT_STRATEGY) or DEFAULT_STRATEGY).strip().lower()
    if value in DISABLED_STRATEGIES:
        return "none"
    if value in ENABLED_STRATEGIES:
        return value
    return DEFAULT_STRATEGY


def rule_rewrite(question: str) -> str:
    parts = []
    stage = extract_stage(question)
    if stage:
        parts.extend([stage, f"{stage}阶段"])
    for marker, expansion in TARGET_HINTS:
        if marker in question:
            parts.extend([marker, expansion])
    tokens = [token for token in tokenize(question) if token not in {"的", "有", "哪", "些", "吗", "呢", "是", "什么"}]
    parts.extend(tokens)
    deduped = dedupe(parts)
    return " ".join(deduped) if deduped else question


def extract_stage(question: str) -> str:
    match = STAGE_PATTERN.search(question or "")
    return match.group(1).strip() if match else ""


def rewrite_with_llm(question: str, context: dict | None = None) -> dict:
    if not settings.LLM_COMPRESSION_API_KEY:
        logger.warning("llm query rewrite skipped: missing LLM_COMPRESSION_API_KEY/DEEPSEEK_API_KEY")
        return build_result(question, rule_rewrite(question), "llm_fallback_rule")
    try:
        client = OpenAI(
            api_key=settings.LLM_COMPRESSION_API_KEY,
            base_url=settings.LLM_COMPRESSION_API_BASE,
            timeout=settings.LLM_COMPRESSION_TIMEOUT,
        )
        prompt = (
            "你是 RAG 检索查询改写器。"
            "请把用户问题改写成适合 BM25 和向量检索的简短关键词查询。\n"
            "要求：保留原意，不要编造文档中未出现的答案，"
            "尽量输出空格分隔的关键词或短语，不要解释。\n\n"
            f"用户问题：{question}\n"
            "改写后查询："
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
            **(context or {}),
        )
        rewritten = (response.choices[0].message.content or "").strip()
        return build_result(question, rewritten or rule_rewrite(question), "llm")
    except Exception as exc:
        record_model_call(
            call_type="rewrite",
            model=settings.LLM_COMPRESSION_MODEL,
            provider="openai_compatible",
            status="failed",
            error_message=str(exc),
            **(context or {}),
        )
        logger.warning("llm query rewrite failed fallback=rule error=%s", exc)
        return build_result(question, rule_rewrite(question), "llm_fallback_rule")


def build_result(original: str, rewritten: str, strategy: str) -> dict:
    return {
        "original_query": original,
        "rewritten_query": rewritten or original,
        "rewrite_strategy": strategy,
    }


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    results = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        results.append(text)
    return results
