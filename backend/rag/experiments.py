from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass

from django.core.management import call_command
from django.db import close_old_connections
from django.utils import timezone

from .eval_runs import reconcile_stale_eval_run

DEFAULT_METRICS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


@dataclass
class ExperimentPlanResult:
    plan: RagExperimentPlan
    action: RagAgentAction | None = None


def create_experiment_plan(*, user, kb_id: int, baseline_run_id: int, goal: str) -> ExperimentPlanResult:
    kb = KnowledgeBase.objects.filter(id=kb_id, owner=user).first()
    if not kb:
        raise ValueError("Knowledge base not found.")
    baseline = (
        RagEvalRun.objects.filter(id=baseline_run_id, kb=kb)
        .prefetch_related("case_results")
        .first()
    )
    if not baseline:
        raise ValueError("Baseline eval run not found.")
    if baseline.status != "completed":
        raise ValueError("Baseline run must be completed before creating experiments.")

    failure_cases = collect_failure_cases(baseline)
    failure_summary = summarize_failures(failure_cases)
    variants = propose_variants(baseline.settings or {}, failure_summary)
    plan = RagExperimentPlan.objects.create(
        owner=user,
        kb=kb,
        baseline_run=baseline,
        goal=goal.strip(),
        status="pending_confirmation",
        failure_cases=failure_cases,
        failure_summary=failure_summary,
    )
    for variant in variants:
        RagExperimentVariant.objects.create(plan=plan, **variant)

    return ExperimentPlanResult(plan=plan)


def collect_failure_cases(run: RagEvalRun, limit: int = 12) -> list[dict]:
    failures = []
    for item in run.case_results.all():
        diagnostics = item.diagnostics or {}
        failed_stages = []
        for stage in ["vector", "bm25", "hybrid", "rerank", "compression", "final_answer"]:
            data = diagnostics.get(stage) or {}
            if data.get("hit") is False or data.get("correct") is False:
                failed_stages.append(stage)
        if item.error_message:
            failed_stages.append("case_error")
        if failed_stages:
            failures.append(
                {
                    "id": item.id,
                    "case_id": item.case_id,
                    "question": item.question,
                    "failed_stages": sorted(set(failed_stages)),
                    "scores": item.scores,
                }
            )
    return failures[:limit]


def summarize_failures(failure_cases: list[dict]) -> dict:
    counter = Counter()
    for case in failure_cases:
        counter.update(case.get("failed_stages") or [])
    return {
        "failed_case_count": len(failure_cases),
        "stage_counts": dict(counter),
        "primary_stage": counter.most_common(1)[0][0] if counter else "unknown",
    }


def base_options(settings: dict) -> dict:
    return {
        "query_rewrite_strategy": settings.get("query_rewrite_strategy") or "rule",
        "top_k": int(settings.get("top_k") or 5),
        "bm25_top_k": int(settings.get("bm25_top_k") or 5),
        "rrf_k": int(settings.get("rrf_k") or 60),
        "rerank_top_n": int(settings.get("rerank_top_n") or 5),
        "compression_strategy": settings.get("compression_strategy") or "structure_aware",
    }


def propose_variants(settings: dict, failure_summary: dict) -> list[dict]:
    base = base_options(settings)
    primary = failure_summary.get("primary_stage")
    variants = []

    recall = {**base}
    recall["top_k"] = min(max(base["top_k"] + 3, 8), 12)
    recall["bm25_top_k"] = min(max(base["bm25_top_k"] + 3, 8), 12)
    recall["rerank_top_n"] = min(max(base["rerank_top_n"] + 2, 6), 10)
    variants.append(
        {
            "name": "召回增强方案",
            "hypothesis": "扩大 Vector/BM25 候选并提高 Rerank 保留数量，验证是否能减少召回缺失和 Rerank 丢失。",
            "rag_options": recall,
        }
    )

    rewrite = {**base}
    rewrite["query_rewrite_strategy"] = "llm" if base.get("query_rewrite_strategy") != "llm" else "rule"
    rewrite["bm25_top_k"] = min(max(base["bm25_top_k"] + 2, 7), 10)
    variants.append(
        {
            "name": "查询改写增强方案",
            "hypothesis": "切换 Query Rewrite 策略并略增 BM25 候选，验证是否能改善问题语义和关键词召回稳定性。",
            "rag_options": rewrite,
        }
    )

    compression = {**base}
    compression["compression_strategy"] = "none" if primary == "compression" else "sentence_filter"
    compression["rerank_top_n"] = min(max(base["rerank_top_n"] + 1, 6), 8)
    variants.append(
        {
            "name": "上下文保真方案",
            "hypothesis": "降低压缩带来的信息损失，验证关键句是否能被保留到最终 Prompt。",
            "rag_options": compression,
        }
    )
    return variants[:3]


def create_experiment_action(*, user, plan: RagExperimentPlan) -> RagAgentAction:
    payload = {"experiment_plan": plan.id, "baseline_run": plan.baseline_run_id, "variant_count": plan.variants.count()}
    action, created = RagAgentAction.objects.get_or_create(
        owner=user,
        action_uid=f"experiment-plan-{plan.id}-run",
        defaults={
            "kb": plan.kb,
            "eval_run": plan.baseline_run,
            "action_type": "run_experiment_plan",
            "source": "experiment_plan",
            "title": "运行参数实验计划",
            "description": f"Agent 已基于 Baseline Run #{plan.baseline_run_id} 生成 {plan.variants.count()} 套参数实验方案。确认后会批量创建 Eval Run。",
            "confirm_label": "确认运行实验",
            "payload": payload,
            "status": "pending",
        },
    )
    if not created and action.status in {"pending", "failed"}:
        action.payload = payload
        action.status = "pending"
        action.error_message = ""
        action.result = {}
        action.completed_at = None
        action.save(update_fields=["payload", "status", "error_message", "result", "completed_at", "updated_at"])
    return action


def start_experiment_plan(*, user, plan_id: int) -> RagExperimentPlan:
    plan = (
        RagExperimentPlan.objects.filter(id=plan_id, owner=user)
        .select_related("kb", "baseline_run")
        .prefetch_related("variants")
        .first()
    )
    if not plan:
        raise ValueError("Experiment plan not found.")
    if plan.status == "completed":
        return plan
    plan.status = "running"
    plan.started_at = timezone.now()
    plan.error_message = ""
    plan.save(update_fields=["status", "started_at", "error_message", "updated_at"])
    suite = (plan.baseline_run.settings or {}).get("suite") or "benchmark"

    for variant in plan.variants.all():
        if variant.eval_run_id:
            continue
        eval_run = RagEvalRun.objects.create(
            kb=plan.kb,
            baseline_run=plan.baseline_run,
            status="running",
            metrics=DEFAULT_METRICS,
            settings={
                "trigger": "agent_experiment_plan",
                "experiment_plan": plan.id,
                "experiment_variant": variant.id,
                "requested_options": {"kb_id": plan.kb_id, "suite": suite, **(variant.rag_options or {})},
            },
            case_count=0,
        )
        variant.eval_run = eval_run
        variant.save(update_fields=["eval_run", "updated_at"])
        command_options = {"kb_id": plan.kb_id, "suite": suite, "run_id": eval_run.id, **(variant.rag_options or {})}
        start_eval_thread(eval_run.id, command_options)
    return plan


def start_eval_thread(run_id: int, command_options: dict):
    def runner():
        close_old_connections()
        try:
            call_command("eval_ragas", **command_options)
        except Exception as exc:
            RagEvalRun.objects.filter(id=run_id).update(status="failed", error_message=str(exc), finished_at=timezone.now())
        finally:
            close_old_connections()

    threading.Thread(target=runner, daemon=True).start()


def refresh_experiment_plan(plan: RagExperimentPlan) -> RagExperimentPlan:
    plan = (
        RagExperimentPlan.objects.filter(id=plan.id)
        .select_related("baseline_run", "winner_variant")
        .prefetch_related("variants__eval_run__case_results")
        .first()
    )
    if not plan:
        return plan
    if plan.status not in {"running", "completed"}:
        return plan
    variants = list(plan.variants.all())
    if not variants or any(not variant.eval_run_id for variant in variants):
        return plan
    for variant in variants:
        if variant.eval_run:
            reconcile_stale_eval_run(variant.eval_run)
    variants = list(plan.variants.select_related("eval_run").all())
    if any(variant.eval_run and variant.eval_run.status == "running" for variant in variants):
        return plan

    for variant in variants:
        variant.result_summary = summarize_variant(plan.baseline_run, variant.eval_run)
        variant.is_winner = False
        variant.save(update_fields=["result_summary", "is_winner", "updated_at"])

    winner = choose_winner(variants)
    if winner:
        winner.is_winner = True
        winner.save(update_fields=["is_winner", "updated_at"])
        plan.winner_variant = winner
        plan.recommendation = {
            "winner_variant": winner.id,
            "winner_name": winner.name,
            "reason": winner.result_summary.get("recommendation_reason", ""),
        }
    plan.status = "completed" if all(v.eval_run and v.eval_run.status == "completed" for v in variants) else "failed"
    plan.completed_at = timezone.now()
    plan.save(update_fields=["status", "winner_variant", "recommendation", "completed_at", "updated_at"])
    finalize_experiment_plan_action(plan)
    return plan


def finalize_experiment_plan_action(plan: RagExperimentPlan) -> None:
    from .models import RagAgentAction

    action = (
        RagAgentAction.objects.filter(
            action_type="run_experiment_plan",
            payload__experiment_plan=plan.id,
            status="running",
        )
        .order_by("-updated_at")
        .first()
    )
    if not action:
        return
    action.status = "completed" if plan.status == "completed" else "failed"
    action.completed_at = timezone.now()
    action.result = {
        **(action.result or {}),
        "plan_id": plan.id,
        "status": plan.status,
        "winner_name": (plan.recommendation or {}).get("winner_name"),
    }
    if plan.status == "failed":
        action.error_message = action.error_message or "实验计划执行失败，请刷新计划查看各 Variant 状态。"
    else:
        action.error_message = ""
    action.save(update_fields=["status", "completed_at", "result", "error_message", "updated_at"])


def summarize_variant(baseline: RagEvalRun, run: RagEvalRun | None) -> dict:
    if not run:
        return {"status": "not_started"}
    baseline_score = average_score(baseline.mean_scores or {})
    run_score = average_score(run.mean_scores or {})
    baseline_failed = failed_count(baseline)
    run_failed = failed_count(run)
    return {
        "status": run.status,
        "mean_score": run_score,
        "baseline_mean_score": baseline_score,
        "score_delta": round(run_score - baseline_score, 6),
        "failed_count": run_failed,
        "baseline_failed_count": baseline_failed,
        "failed_delta": run_failed - baseline_failed,
        "recommendation_reason": f"平均分变化 {run_score - baseline_score:+.3f}，失败数变化 {run_failed - baseline_failed:+d}。",
    }


def average_score(scores: dict) -> float:
    values = [float(value) for value in (scores or {}).values() if isinstance(value, (int, float))]
    return round(sum(values) / len(values), 6) if values else 0.0


def failed_count(run: RagEvalRun) -> int:
    count = 0
    for item in run.case_results.all():
        final = (item.diagnostics or {}).get("final_answer") or {}
        if final.get("correct") is False or item.error_message:
            count += 1
    return count


def choose_winner(variants: list[RagExperimentVariant]) -> RagExperimentVariant | None:
    completed = [item for item in variants if item.eval_run and item.eval_run.status == "completed"]
    if not completed:
        return None
    return sorted(
        completed,
        key=lambda item: (
            item.result_summary.get("score_delta", 0),
            -item.result_summary.get("failed_count", 9999),
        ),
        reverse=True,
    )[0]
