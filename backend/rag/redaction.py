from __future__ import annotations

import hashlib
import re

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
ID_RE = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
BANK_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")
SALARY_RE = re.compile(r"(?i)((?:工资|薪资|薪酬|salary|compensation)[^\n]{0,20}?)(?:¥|￥|RMB\s*)?\d+(?:[,.]\d+)?(?:元|万|k)?")


def redact_sensitive_text(value: str, limit: int = 500) -> tuple[str, dict]:
    text = str(value or "")
    counts = {}
    for name, pattern, replacement in [
        ("email", EMAIL_RE, "[REDACTED_EMAIL]"),
        ("phone", PHONE_RE, "[REDACTED_PHONE]"),
        ("id", ID_RE, "[REDACTED_ID]"),
        ("bank", BANK_RE, "[REDACTED_BANK]"),
        ("salary", SALARY_RE, r"\1[REDACTED_AMOUNT]"),
    ]:
        text, count = pattern.subn(replacement, text)
        if count:
            counts[name] = count
    truncated = len(text) > limit
    if truncated:
        text = text[:limit] + "..."
    return text, {
        "redacted": counts,
        "truncated": truncated,
        "original_length": len(str(value or "")),
        "sha256": hashlib.sha256(str(value or "").encode()).hexdigest(),
    }


def sanitize_retrieval_item(item: dict) -> dict:
    content = str(item.get("content") or "")
    redacted, metadata = redact_sensitive_text(content, limit=220)
    return {
        key: value for key, value in item.items()
        if key in {"rank", "chunk_id", "document", "score", "engine", "location", "matched_terms", "metadata"}
    } | {"snippet": redacted, "content_length": len(content), "content_hash": metadata["sha256"]}


def sanitize_trace_results(items: list[dict]) -> list[dict]:
    return [sanitize_retrieval_item(item) for item in (items or [])]
