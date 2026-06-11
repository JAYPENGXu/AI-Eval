from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any

from django.conf import settings

from .models import ModelCallLog

logger = logging.getLogger(__name__)


def now_ms() -> float:
    return perf_counter()


def elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def extract_usage(response: Any) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    return normalize_usage(usage)


def normalize_usage(usage: Any) -> dict:
    if not usage:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if isinstance(usage, dict):
        getter = usage.get
    else:
        getter = lambda key, default=0: getattr(usage, key, default)
    prompt_tokens = int(getter("prompt_tokens", getter("input_tokens", 0)) or 0)
    completion_tokens = int(getter("completion_tokens", getter("output_tokens", 0)) or 0)
    total_tokens = int(getter("total_tokens", 0) or 0)
    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    config = getattr(settings, "MODEL_TOKEN_PRICES", {}) or {}
    price = config.get(model) or config.get(sanitize_model_name(model)) or {}
    input_price = float(price.get("input_per_1k", price.get("prompt_per_1k", 0)) or 0)
    output_price = float(price.get("output_per_1k", price.get("completion_per_1k", 0)) or 0)
    return round((prompt_tokens / 1000 * input_price) + (completion_tokens / 1000 * output_price), 8)


def sanitize_model_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", model or "").strip("_").upper()


def infer_owner(owner=None, kb=None, session=None, trace=None, message=None, eval_run=None):
    if owner:
        return owner
    if kb:
        return kb.owner
    if session:
        return session.owner
    if trace:
        return trace.session.owner
    if message:
        return message.session.owner
    if eval_run:
        return eval_run.kb.owner
    return None


def record_model_call(
    *,
    call_type: str,
    model: str,
    provider: str = "",
    status: str = "completed",
    usage: Any = None,
    latency_ms: int = 0,
    error_message: str = "",
    owner=None,
    kb=None,
    session=None,
    message=None,
    trace=None,
    eval_run=None,
    metadata: dict | None = None,
) -> ModelCallLog | None:
    usage_data = normalize_usage(usage)
    prompt_tokens = usage_data["prompt_tokens"]
    completion_tokens = usage_data["completion_tokens"]
    try:
        return ModelCallLog.objects.create(
            owner=infer_owner(owner, kb, session, trace, message, eval_run),
            kb=kb or getattr(session, "kb", None) or getattr(getattr(trace, "session", None), "kb", None) or getattr(eval_run, "kb", None),
            session=session or getattr(trace, "session", None) or getattr(message, "session", None),
            message=message,
            trace=trace,
            eval_run=eval_run,
            provider=provider,
            model=model or "",
            call_type=call_type,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=usage_data["total_tokens"],
            estimated_cost=estimate_cost(model, prompt_tokens, completion_tokens),
            latency_ms=max(0, int(latency_ms or 0)),
            error_message=str(error_message or "")[:4000],
            metadata=metadata or {},
        )
    except Exception as exc:
        logger.warning("failed to record model call usage: %s", exc)
        return None
