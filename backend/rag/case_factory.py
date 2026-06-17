from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import RagBenchmarkCase, RagEvalCaseResult, RagTrace


@dataclass
class CaseCreateResult:
    case: RagBenchmarkCase
    created: bool


def create_regression_case_from_trace(*, user, trace_id: int, payload: dict[str, Any] | None = None) -> CaseCreateResult:
    payload = payload or {}
    trace = (
        RagTrace.objects.filter(id=trace_id, session__owner=user)
        .select_related("session", "session__kb", "message")
        .first()
    )
    if not trace:
        raise ValueError("Trace not found.")

    case_id = payload.get("case_id") or f"trace_{trace.id}"
    trace_answer = trace.message.content if trace.message else ""
    reference = payload.get("reference") or trace_answer or "TODO: please review reference answer."
    defaults = {
        "question": trace.question,
        "reference": reference,
        "tags": payload.get("tags") or ["trace", "regression"],
        "expected_terms": payload.get("expected_terms") or [],
        "target_chunk_ids": payload.get("target_chunk_ids") or [],
        "suite": payload.get("suite") or "regression",
        "source": "trace",
        "notes": payload.get("notes") or f"Created from Trace #{trace.id}. Please review reference and target chunks.",
        "difficulty": payload.get("difficulty") or "medium",
        "enabled": payload.get("enabled", False),
        "metadata": {
            "trace_id": trace.id,
            "session_id": trace.session_id,
            "message_id": trace.message_id,
            "created_from": "trace",
            "failure_signals": payload.get("failure_signals") or [],
        },
    }
    case, created = RagBenchmarkCase.objects.update_or_create(
        kb=trace.session.kb,
        case_id=case_id,
        defaults=defaults,
    )
    return CaseCreateResult(case=case, created=created)


def create_regression_case_from_eval_case(*, user, eval_case_result_id: int, payload: dict[str, Any] | None = None) -> CaseCreateResult:
    payload = payload or {}
    result = (
        RagEvalCaseResult.objects.filter(id=eval_case_result_id, run__kb__owner=user)
        .select_related("run", "run__kb")
        .first()
    )
    if not result:
        raise ValueError("Eval case result not found.")

    diagnostics = result.diagnostics or {}
    stages = diagnostics.get("stages") or {}
    failed_stages = [key for key, value in stages.items() if not value.get("hit")]
    final_answer = diagnostics.get("final_answer") or {}
    if final_answer and not final_answer.get("correct"):
        failed_stages.append("final_answer")

    expected_terms = diagnostics.get("expected_terms") or diagnostics.get("reference_terms") or []
    target_chunk_ids = diagnostics.get("target_chunk_ids") or []
    if not target_chunk_ids:
        for value in stages.values():
            target_chunk_ids = value.get("target_chunk_ids") or []
            if target_chunk_ids:
                break

    raw_case_id = result.case_id or f"eval_case_{result.id}"
    case_id = payload.get("case_id") or f"regression_{raw_case_id}"
    defaults = {
        "question": result.question,
        "reference": result.reference or "TODO: please review reference answer.",
        "tags": payload.get("tags") or ["eval_failure", "regression"],
        "expected_terms": payload.get("expected_terms") or expected_terms,
        "target_chunk_ids": payload.get("target_chunk_ids") or target_chunk_ids,
        "suite": payload.get("suite") or "regression",
        "source": "eval_failure",
        "notes": payload.get("notes") or f"Created from Eval Run #{result.run_id}, case {result.case_id}. Failed stages: {', '.join(failed_stages) or 'unknown'}.",
        "difficulty": payload.get("difficulty") or "medium",
        "enabled": payload.get("enabled", True),
        "metadata": {
            "eval_run_id": result.run_id,
            "eval_case_result_id": result.id,
            "failed_stages": failed_stages,
            "created_from": "eval_failure",
            "failure_signals": payload.get("failure_signals") or [],
        },
    }
    case, created = RagBenchmarkCase.objects.update_or_create(
        kb=result.run.kb,
        case_id=case_id,
        defaults=defaults,
    )
    return CaseCreateResult(case=case, created=created)



def create_regression_case_from_user_feedback(*, user, feedback_id: int, payload: dict[str, Any] | None = None) -> CaseCreateResult:
    from .models import RagUserFeedback

    payload = payload or {}
    feedback = (
        RagUserFeedback.objects.filter(id=feedback_id, owner=user)
        .select_related("message", "session", "session__kb", "trace")
        .first()
    )
    if not feedback:
        raise ValueError("User feedback not found.")
    if not feedback.trace:
        raise ValueError("Feedback has no trace.")

    trace = feedback.trace
    case_id = payload.get("case_id") or f"feedback_{feedback.id}_trace_{trace.id}"
    reference = payload.get("reference") or feedback.message.content or "TODO: please review reference answer."
    defaults = {
        "question": trace.question,
        "reference": reference,
        "tags": payload.get("tags") or ["user_feedback", "regression", feedback.reason or feedback.rating],
        "expected_terms": payload.get("expected_terms") or [],
        "target_chunk_ids": payload.get("target_chunk_ids") or [],
        "suite": payload.get("suite") or "regression",
        "source": "user_feedback",
        "notes": payload.get("notes") or f"Created from user feedback #{feedback.id}. Reason: {feedback.reason or feedback.rating}. Please review reference and target chunks.",
        "difficulty": payload.get("difficulty") or "medium",
        "enabled": payload.get("enabled", True),
        "metadata": {
            "feedback_id": feedback.id,
            "trace_id": trace.id,
            "message_id": feedback.message_id,
            "reason": feedback.reason,
            "rating": feedback.rating,
            "failure_signals": payload.get("failure_signals") or feedback.failure_signals,
            "created_from": "user_feedback",
        },
    }
    case, created = RagBenchmarkCase.objects.update_or_create(
        kb=feedback.session.kb,
        case_id=case_id,
        defaults=defaults,
    )
    return CaseCreateResult(case=case, created=created)
