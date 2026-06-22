from __future__ import annotations

from django.db.models import Avg, Count, Sum

from rag.access_control import build_access_scope, filter_knowledge_bases_for_user, filter_traces_for_user
from rag.models import ModelCallLog, RagEvalRun, RagTrace


def compact_text(value: str, limit: int = 1200) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def compact_sources(items: list[dict], limit: int = 5) -> list[dict]:
    results = []
    for item in (items or [])[:limit]:
        results.append(
            {
                "rank": item.get("rank"),
                "chunk_id": item.get("chunk_id"),
                "document": item.get("document"),
                "engine": item.get("engine"),
                "score": item.get("score"),
                "rrf_score": item.get("rrf_score"),
                "rerank_score": item.get("rerank_score"),
                "pre_rerank_rank": item.get("pre_rerank_rank"),
                "snippet": compact_text(item.get("snippet"), 220),
                "matched_terms": item.get("matched_terms") or [],
                "sources": item.get("sources") or {},
                "location": item.get("location") or {},
                "original_tokens": item.get("original_tokens"),
                "compressed_tokens": item.get("compressed_tokens"),
                "compression_ratio": item.get("compression_ratio"),
            }
        )
    return results


def get_trace_detail(*, user, trace_id: int) -> dict:
    trace = (
        filter_traces_for_user(user, RagTrace.objects.filter(id=trace_id))
        .select_related("session", "session__kb", "message")
        .first()
    )
    if not trace:
        return {"ok": False, "error": "Trace not found."}
    return {
        "ok": True,
        "trace": {
            "id": trace.id,
            "kb_id": trace.session.kb_id,
            "kb_name": trace.session.kb.name,
            "question": trace.question,
            "answer": compact_text(trace.message.content if trace.message else "", 1600),
            "rewritten_query": trace.rewritten_query,
            "retrieval_mode": trace.retrieval_mode,
            "vector_results": compact_sources(trace.vector_results),
            "bm25_results": compact_sources(trace.bm25_results),
            "hybrid_results": compact_sources(trace.hybrid_results),
            "rerank_results": compact_sources(trace.rerank_results),
            "compression_results": compact_sources(trace.compression_results),
            "compression_stats": trace.compression_stats,
            "settings": trace.settings,
            "final_prompt_excerpt": "",
        },
    }


def get_model_usage_summary(*, user, kb_id: int | None = None, trace_id: int | None = None) -> dict:
    queryset = ModelCallLog.objects.filter(owner=user)
    if kb_id:
        queryset = queryset.filter(kb_id=kb_id)
    if trace_id:
        queryset = queryset.filter(trace_id=trace_id)
    totals = queryset.aggregate(
        call_count=Count("id"),
        total_tokens=Sum("total_tokens"),
        prompt_tokens=Sum("prompt_tokens"),
        completion_tokens=Sum("completion_tokens"),
        estimated_cost=Sum("estimated_cost"),
        avg_latency_ms=Avg("latency_ms"),
    )
    by_model = list(
        queryset.values("model", "call_type")
        .annotate(
            call_count=Count("id"),
            total_tokens=Sum("total_tokens"),
            estimated_cost=Sum("estimated_cost"),
            avg_latency_ms=Avg("latency_ms"),
        )
        .order_by("-estimated_cost", "-total_tokens")[:10]
    )
    slow_calls = list(
        queryset.order_by("-latency_ms")
        .values("id", "model", "call_type", "latency_ms", "total_tokens", "estimated_cost", "trace_id")[:8]
    )
    failed_calls = list(
        queryset.filter(status="failed")
        .order_by("-created_at")
        .values("id", "model", "call_type", "error_message", "trace_id", "created_at")[:8]
    )
    return {
        "ok": True,
        "totals": {
            "call_count": totals["call_count"] or 0,
            "total_tokens": totals["total_tokens"] or 0,
            "prompt_tokens": totals["prompt_tokens"] or 0,
            "completion_tokens": totals["completion_tokens"] or 0,
            "estimated_cost": round(totals["estimated_cost"] or 0, 8),
            "avg_latency_ms": round(totals["avg_latency_ms"] or 0),
        },
        "by_model": by_model,
        "slow_calls": slow_calls,
        "failed_calls": failed_calls,
    }


def compare_eval_runs(*, user, left_run_id: int, right_run_id: int) -> dict:
    runs = list(
        RagEvalRun.objects.filter(id__in=[left_run_id, right_run_id], kb_id__in=filter_knowledge_bases_for_user(user, capability="use_agent").values("id"))
        .select_related("kb")
        .prefetch_related("case_results")
    )
    run_map = {run.id: run for run in runs}
    left = run_map.get(left_run_id)
    right = run_map.get(right_run_id)
    if not left or not right:
        return {"ok": False, "error": "Eval run not found."}

    left_cases = {item.case_id: item for item in left.case_results.all()}
    right_cases = {item.case_id: item for item in right.case_results.all()}
    changed_cases = []
    for case_id in sorted(set(left_cases) & set(right_cases)):
        left_case = left_cases[case_id]
        right_case = right_cases[case_id]
        left_diag = left_case.diagnostics or {}
        right_diag = right_case.diagnostics or {}
        left_correct = (left_diag.get("final_answer") or {}).get("correct")
        right_correct = (right_diag.get("final_answer") or {}).get("correct")
        if left_correct != right_correct:
            changed_cases.append(
                {
                    "case_id": case_id,
                    "left_id": left_case.id,
                    "right_id": right_case.id,
                    "question": right_case.question or left_case.question,
                    "left_correct": left_correct,
                    "right_correct": right_correct,
                    "left_scores": left_case.scores,
                    "right_scores": right_case.scores,
                }
            )

    return {
        "ok": True,
        "left": {
            "id": left.id,
            "status": left.status,
            "mean_scores": left.mean_scores,
            "retrieval_metrics": left.retrieval_metrics,
            "settings": left.settings,
            "case_count": left.case_count,
        },
        "right": {
            "id": right.id,
            "status": right.status,
            "mean_scores": right.mean_scores,
            "retrieval_metrics": right.retrieval_metrics,
            "settings": right.settings,
            "case_count": right.case_count,
        },
        "changed_cases": changed_cases[:12],
    }


TOOL_REGISTRY = {
    "get_trace_detail": get_trace_detail,
    "get_model_usage_summary": get_model_usage_summary,
    "compare_eval_runs": compare_eval_runs,
}
