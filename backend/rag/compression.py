from __future__ import annotations

import re
import logging
import time

from django.conf import settings
from openai import OpenAI

from .bm25 import tokenize
from .model_usage import elapsed_ms, extract_usage, record_model_call


logger = logging.getLogger(__name__)
SENTENCE_PATTERN = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?|[^\n]+")
DISABLED_STRATEGIES = {"none", "disabled", "no_compression", "off"}
ENABLED_STRATEGIES = {"sentence_filter", "structure_aware", "llm"}
DEFAULT_STRATEGY = "structure_aware"
TOOL_HEADING = "使用工具"


def compress_context(
    question: str,
    sources: list[dict],
    *,
    strategy: str | None = None,
    enabled: bool | None = None,
    context: dict | None = None,
) -> tuple[list[dict], dict]:
    selected_strategy = normalize_strategy(strategy)
    compression_enabled = settings.CONTEXT_COMPRESSION_ENABLED if enabled is None else enabled
    if not compression_enabled or selected_strategy in DISABLED_STRATEGIES:
        normalized_sources = [build_uncompressed_source(source) for source in sources]
        return normalized_sources, build_stats(sources, normalized_sources, "none")

    if selected_strategy == "llm":
        return compress_context_with_llm(question, sources, context=context)

    compressed_sources = []
    query_tokens = set(tokenize(question))
    for source in sources:
        compressed_sources.append(compress_source(source, query_tokens, selected_strategy))

    return compressed_sources, build_stats(sources, compressed_sources, selected_strategy)


def normalize_strategy(strategy: str | None) -> str:
    value = (strategy or settings.CONTEXT_COMPRESSION_STRATEGY or DEFAULT_STRATEGY).strip().lower()
    if value in DISABLED_STRATEGIES:
        return "none"
    if value in ENABLED_STRATEGIES:
        return value
    return DEFAULT_STRATEGY


def compress_context_with_llm(question: str, sources: list[dict], context: dict | None = None) -> tuple[list[dict], dict]:
    if not settings.LLM_COMPRESSION_API_KEY:
        logger.warning("llm compression skipped: missing LLM_COMPRESSION_API_KEY/DEEPSEEK_API_KEY")
        fallback_sources = [compress_source(source, set(tokenize(question)), "structure_aware") for source in sources]
        return fallback_sources, build_stats(sources, fallback_sources, "llm_fallback_structure_aware")

    try:
        client = OpenAI(
            api_key=settings.LLM_COMPRESSION_API_KEY,
            base_url=settings.LLM_COMPRESSION_API_BASE,
            timeout=settings.LLM_COMPRESSION_TIMEOUT,
        )
        compressed_sources = [compress_source_with_llm(client, question, source, context=context) for source in sources]
        return compressed_sources, build_stats(sources, compressed_sources, "llm")
    except Exception as exc:
        logger.warning("llm compression failed, fallback to structure_aware: %s", exc)
        fallback_sources = [compress_source(source, set(tokenize(question)), "structure_aware") for source in sources]
        return fallback_sources, build_stats(sources, fallback_sources, "llm_fallback_structure_aware")


def compress_source_with_llm(client: OpenAI, question: str, source: dict, context: dict | None = None) -> dict:
    content = source.get("content") or ""
    original_tokens = estimate_tokens(content)
    if not content:
        return build_uncompressed_source(source)

    prompt = (
        "你是 RAG 上下文压缩器。请只基于原文，抽取回答问题所需的最小片段。\n"
        "要求：\n"
        "1. 尽量保留原文措辞，不要编造。\n"
        "2. 如果命中标题、列表、步骤，请保留必要的相邻列表项。\n"
        "3. 如果原文与问题无关，只返回空字符串。\n"
        "4. 不要解释，不要输出 Markdown 标题，只输出压缩后的上下文文本。\n\n"
        f"问题：{question}\n\n"
        f"原文：\n{content}\n\n"
        "压缩后的上下文："
    )
    started_at = time.perf_counter()
    response = client.chat.completions.create(
        model=settings.LLM_COMPRESSION_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=settings.LLM_COMPRESSION_MAX_OUTPUT_TOKENS,
    )
    record_model_call(
        call_type="compression",
        model=settings.LLM_COMPRESSION_MODEL,
        provider="openai_compatible",
        usage=extract_usage(response),
        latency_ms=elapsed_ms(started_at),
        metadata={"chunk_id": source.get("chunk_id")},
        **(context or {}),
    )
    compressed_content = (response.choices[0].message.content or "").strip()
    if not compressed_content:
        compressed_content = ""
    compressed_tokens = estimate_tokens(compressed_content)
    kept_sentences = split_sentences(compressed_content) if compressed_content else []
    original_sentences = split_sentences(content)

    return {
        **source,
        "content": compressed_content,
        "original_content": content,
        "kept_sentences": kept_sentences,
        "removed_sentences": [sentence for sentence in original_sentences if sentence not in kept_sentences],
        "original_tokens": original_tokens,
        "compressed_tokens": compressed_tokens if compressed_content else 0,
        "compression_ratio": round(1 - compressed_tokens / original_tokens, 4) if original_tokens and compressed_content else 1,
        "llm_compression_model": settings.LLM_COMPRESSION_MODEL,
    }


def build_uncompressed_source(source: dict) -> dict:
    content = source.get("content") or ""
    tokens = estimate_tokens(content)
    return {
        **source,
        "content": content,
        "original_content": content,
        "kept_sentences": split_sentences(content) or ([content] if content else []),
        "removed_sentences": [],
        "original_tokens": tokens,
        "compressed_tokens": tokens,
        "compression_ratio": 0,
    }


def compress_source(source: dict, query_tokens: set[str], strategy: str) -> dict:
    content = source.get("content") or ""
    sentences = split_sentences(content)
    if not sentences:
        return {
            **source,
            "original_content": content,
            "kept_sentences": [],
            "removed_sentences": [],
            "original_tokens": estimate_tokens(content),
            "compressed_tokens": 0,
            "compression_ratio": 0,
        }

    scored = score_sentences(sentences, query_tokens)
    positive = [item for item in scored if item[0] >= settings.COMPRESSION_MIN_SCORE]
    candidates = positive or sorted(scored, key=lambda item: item[0], reverse=True)[:1]
    selected_base = sorted(candidates, key=lambda item: (-item[0], item[1]))[
        : settings.COMPRESSION_MAX_SENTENCES_PER_CHUNK
    ]
    base_indexes = {index for _, index, _ in selected_base}

    if strategy == "structure_aware":
        kept_indexes = expand_structured_neighbors(base_indexes, sentences)
    else:
        kept_indexes = expand_sentence_window(base_indexes, len(sentences))

    kept_indexes = trim_indexes(kept_indexes, base_indexes, scored, sentences, strategy)
    kept_sentences = [sentence for index, sentence in enumerate(sentences) if index in kept_indexes]
    removed_sentences = [sentence for index, sentence in enumerate(sentences) if index not in kept_indexes]
    compressed_content = "\n".join(kept_sentences).strip()
    original_tokens = estimate_tokens(content)
    compressed_tokens = estimate_tokens(compressed_content)

    return {
        **source,
        "content": compressed_content or content,
        "original_content": content,
        "kept_sentences": kept_sentences,
        "removed_sentences": removed_sentences,
        "original_tokens": original_tokens,
        "compressed_tokens": compressed_tokens,
        "compression_ratio": round(1 - compressed_tokens / original_tokens, 4) if original_tokens else 0,
    }


def score_sentences(sentences: list[str], query_tokens: set[str]) -> list[tuple[float, int, str]]:
    scored = []
    for index, sentence in enumerate(sentences):
        sentence_tokens = set(tokenize(sentence))
        overlap = len(query_tokens & sentence_tokens)
        score = overlap / max(len(query_tokens), 1)
        scored.append((score, index, sentence))
    return scored


def trim_indexes(
    kept_indexes: set[int],
    base_indexes: set[int],
    scored: list[tuple[float, int, str]],
    sentences: list[str],
    strategy: str,
) -> set[int]:
    if len(kept_indexes) <= settings.COMPRESSION_MAX_SENTENCES_PER_CHUNK:
        return kept_indexes

    protected_indexes = collect_protected_indexes(base_indexes, sentences) if strategy == "structure_aware" else set()
    ranked_indexes = []
    score_by_index = {index: score for score, index, _ in scored}
    anchor = min(kept_indexes)
    for index in kept_indexes:
        if index in protected_indexes:
            continue
        ranked_indexes.append((score_by_index.get(index, 0), -abs(index - anchor), index))
    ranked_indexes.sort(reverse=True)
    remaining_slots = max(settings.COMPRESSION_MAX_SENTENCES_PER_CHUNK - len(protected_indexes), 0)
    return protected_indexes | {index for _, _, index in ranked_indexes[:remaining_slots]}


def split_sentences(text: str) -> list[str]:
    return [match.group(0).strip() for match in SENTENCE_PATTERN.finditer(text or "") if match.group(0).strip()]


def expand_sentence_window(indexes: set[int], sentence_count: int) -> set[int]:
    expanded = set(indexes)
    window = max(0, settings.COMPRESSION_SENTENCE_WINDOW)
    for index in indexes:
        start = max(0, index - 1)
        end = min(sentence_count, index + window + 1)
        expanded.update(range(start, end))
    return expanded


def expand_structured_neighbors(indexes: set[int], sentences: list[str]) -> set[int]:
    expanded = expand_sentence_window(indexes, len(sentences))
    expanded.update(collect_protected_indexes(indexes, sentences))
    return expanded


def collect_protected_indexes(indexes: set[int], sentences: list[str]) -> set[int]:
    protected = set()
    for index in indexes:
        protected.update(expand_list_block(index, sentences))
        nearby_start = max(0, index - 2)
        nearby_end = min(len(sentences), index + settings.COMPRESSION_SENTENCE_WINDOW + 1)
        for nearby_index in range(nearby_start, nearby_end):
            if is_section_heading(sentences[nearby_index]) or TOOL_HEADING in sentences[nearby_index]:
                protected.update(expand_list_block(nearby_index, sentences))
    return protected


def expand_list_block(index: int, sentences: list[str]) -> set[int]:
    if index < 0 or index >= len(sentences):
        return set()

    protected = {index}
    sentence = sentences[index]
    if not (is_section_heading(sentence) or TOOL_HEADING in sentence):
        return protected

    max_items = max(0, settings.COMPRESSION_LIST_ITEM_WINDOW)
    item_count = 0
    for next_index in range(index + 1, len(sentences)):
        next_sentence = sentences[next_index]
        if item_count > 0 and is_section_heading(next_sentence):
            break
        protected.add(next_index)
        item_count += 1
        if item_count >= max_items:
            break
    return protected


def is_section_heading(sentence: str) -> bool:
    text = sentence.strip()
    if not text or len(text) > 40:
        return False
    return text.endswith((":", "："))


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    tokens = tokenize(text)
    return max(len(tokens), 1)


def build_stats(original_sources: list[dict], compressed_sources: list[dict], strategy: str) -> dict:
    original_tokens = sum(estimate_tokens(source.get("content", "")) for source in original_sources)
    compressed_tokens = sum(estimate_tokens(source.get("content", "")) for source in compressed_sources)
    saved_tokens = max(original_tokens - compressed_tokens, 0)
    return {
        "strategy": strategy,
        "original_tokens": original_tokens,
        "compressed_tokens": compressed_tokens,
        "saved_tokens": saved_tokens,
        "saving_ratio": round(saved_tokens / original_tokens, 4) if original_tokens else 0,
        "chunk_count": len(compressed_sources),
    }
