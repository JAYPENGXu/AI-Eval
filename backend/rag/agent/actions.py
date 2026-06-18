from __future__ import annotations

from django.utils import timezone

from rag.case_factory import (
    create_regression_case_from_eval_case,
    create_regression_case_from_trace,
    create_regression_case_from_user_feedback,
)
from rag.experiments import start_experiment_plan
from rag.models import RagAgentAction


def execute_agent_action(*, user, action: RagAgentAction) -> dict:
    """Execute a confirmed RagAgentAction and persist status/result on the model."""
    if action.status == "completed":
        return action.result or {"already_completed": True}
    if action.status == "rejected":
        raise ValueError("Rejected actions cannot be executed.")
    if action.status == "running" and action.action_type == "run_experiment_plan":
        return action.result or {"plan_id": action.payload.get("experiment_plan"), "status": "running"}

    action.confirmed_at = action.confirmed_at or timezone.now()
    action.error_message = ""
    action.save(update_fields=["confirmed_at", "error_message", "updated_at"])

    if action.action_type == "run_experiment_plan":
        plan_id = action.payload.get("experiment_plan")
        plan = start_experiment_plan(user=user, plan_id=int(plan_id))
        action.status = "running"
        action.result = {
            "plan_id": plan.id,
            "status": plan.status,
            "variant_count": plan.variants.count(),
        }
        action.save(update_fields=["status", "result", "updated_at"])
        return action.result

    if action.action_type != "create_regression_case":
        raise ValueError(f"Unsupported action type: {action.action_type}")

    if action.source == "trace":
        trace_id = action.payload.get("trace") or action.trace_id
        result = create_regression_case_from_trace(user=user, trace_id=int(trace_id), payload=action.payload)
    elif action.source == "eval_failure":
        eval_case_id = action.payload.get("eval_case") or action.eval_case_result_id
        result = create_regression_case_from_eval_case(
            user=user,
            eval_case_result_id=int(eval_case_id),
            payload=action.payload,
        )
    elif action.source == "user_feedback":
        feedback_id = action.payload.get("feedback")
        result = create_regression_case_from_user_feedback(
            user=user,
            feedback_id=int(feedback_id),
            payload=action.payload,
        )
    else:
        raise ValueError(f"Unsupported action source: {action.source}")

    action.status = "completed"
    action.created_case = result.case
    action.completed_at = timezone.now()
    action.result = {
        "created": result.created,
        "case_id": result.case.case_id,
        "case_pk": result.case.id,
    }
    action.error_message = ""
    action.save(
        update_fields=[
            "status",
            "created_case",
            "completed_at",
            "result",
            "error_message",
            "updated_at",
        ]
    )
    return action.result
