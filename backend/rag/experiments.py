from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.utils import timezone

from .eval_runs import reconcile_stale_eval_run
from .models import KnowledgeBase, RagAgentAction, RagBenchmarkCase, RagConfigVersion, RagEvalRun, RagExperimentPlan, RagExperimentVariant

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
            status="queued",
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
        command_options = {"kb_id": plan.kb_id, "suite": suite, **(variant.rag_options or {})}
        from .tasks import run_eval_task
        try:
            result = run_eval_task.apply_async(args=[eval_run.id, command_options], queue="evaluations")
            eval_run.celery_task_id = result.id
            eval_run.save(update_fields=["celery_task_id"])
        except Exception as exc:
            eval_run.status = "failed"
            eval_run.error_message = f"实验评测任务入队失败：{exc}"
            eval_run.finished_at = timezone.now()
            eval_run.save(update_fields=["status", "error_message", "finished_at"])
    from .tasks import finalize_experiment_plan_task
    finalize_experiment_plan_task.apply_async(args=[plan.id], countdown=1, queue="orchestration")
    return plan


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
    candidate = RagConfigVersion.objects.filter(experiment_plan=plan).order_by("-version").first()
    if candidate:
        finalize_release_candidate(candidate)
        return plan
    variants = list(plan.variants.all())
    if not variants or any(not variant.eval_run_id for variant in variants):
        return plan
    for variant in variants:
        if variant.eval_run:
            reconcile_stale_eval_run(variant.eval_run)
    variants = list(plan.variants.select_related("eval_run").all())
    if any(variant.eval_run and variant.eval_run.status in {"queued", "running"} for variant in variants):
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
    if plan.status == "completed" and winner:
        create_release_candidate(plan, winner)
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
    eligible = []
    for item in variants:
        run = item.eval_run
        summary = item.result_summary or {}
        if not run or run.status != "completed" or summary.get("score_delta", 0) < 0.01 or summary.get("failed_delta", 1) > 0:
            continue
        results = list(run.case_results.all())
        if not results or any(
            result.error_message
            or (result.deterministic_results or {}).get("passed") is False
            or (result.judge_results or {}).get("passed") is False
            for result in results
        ):
            continue
        baseline_latency = float((item.plan.baseline_run.execution_metrics or {}).get("avg_latency_ms") or 0)
        latency = float((run.execution_metrics or {}).get("avg_latency_ms") or 0)
        if baseline_latency and latency > baseline_latency * 1.2:
            continue
        eligible.append(item)
    if not eligible:
        return None
    return sorted(eligible, key=lambda item: (item.result_summary.get("score_delta", 0), -item.result_summary.get("failed_count", 9999)), reverse=True)[0]


def create_release_candidate(plan, winner):
    from .config_versions import create_config_version, ensure_initial_config
    parent = ensure_initial_config(plan.kb, plan.owner)
    candidate = create_config_version(
        kb=plan.kb, payload=winner.rag_options, user=plan.owner, source="experiment", parent=parent,
        experiment_plan=plan, winner_variant=winner,
    )
    release_count = RagBenchmarkCase.objects.filter(kb=plan.kb, suite="release", enabled=True).count()
    if not release_count:
        candidate.validation_status = "release_failed"
        candidate.save(update_fields=["validation_status"])
        plan.recommendation = {**(plan.recommendation or {}), "release_gate": "failed", "release_reason": "没有启用的 release Case。", "candidate_version": candidate.version}
        plan.save(update_fields=["recommendation", "updated_at"])
        return candidate
    run = RagEvalRun.objects.create(
        kb=plan.kb, baseline_run=plan.baseline_run, status="queued", metrics=DEFAULT_METRICS,
        settings={"trigger": "release_gate", "experiment_plan": plan.id, "config_version": candidate.id, "requested_options": {"kb_id": plan.kb_id, "suite": "release", **candidate.payload}},
    )
    candidate.release_eval_run = run; candidate.validation_status = "release_running"
    candidate.save(update_fields=["release_eval_run", "validation_status"])
    from .tasks import run_eval_task
    try:
        result = run_eval_task.apply_async(args=[run.id, {"kb_id": plan.kb_id, "suite": "release", **candidate.payload}], queue="evaluations")
        run.celery_task_id = result.id
        run.save(update_fields=["celery_task_id"])
    except Exception as exc:
        run.status = "failed"; run.error_message = f"Release 评测任务入队失败：{exc}"; run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        candidate.validation_status = "release_failed"
        candidate.save(update_fields=["validation_status"])
        plan.recommendation = {**(plan.recommendation or {}), "release_gate": "failed", "release_reason": run.error_message, "candidate_version": candidate.version}
        plan.save(update_fields=["recommendation", "updated_at"])
        return candidate
    plan.recommendation = {**(plan.recommendation or {}), "release_gate": "running", "candidate_version": candidate.version, "release_eval_run": run.id}
    plan.save(update_fields=["recommendation", "updated_at"])
    return candidate


def finalize_release_candidate(candidate):
    run = candidate.release_eval_run
    if not run or run.status in {"queued", "running"}:
        return
    results = list(run.case_results.all())
    passed = run.status == "completed" and run.case_count > 0 and len(results) > 0 and all(
        not item.error_message
        and (item.deterministic_results or {}).get("passed") is not False
        and (item.judge_results or {}).get("passed") is not False
        for item in results
    )
    regression_reason = ""
    active = candidate.kb.active_config_version
    previous_run = active.release_eval_run if active and active.release_eval_run_id else None
    if passed and previous_run and previous_run.status == "completed":
        previous_score = average_score(previous_run.mean_scores or {})
        current_score = average_score(run.mean_scores or {})
        if current_score < previous_score - 0.01 or failed_count(run) > failed_count(previous_run):
            passed = False
            regression_reason = "Release 相比当前线上版本出现显著评分或失败数回归。"
    candidate.validation_status = "release_passed" if passed else "release_failed"
    candidate.save(update_fields=["validation_status"])
    plan = candidate.experiment_plan
    if plan:
        plan.recommendation = {**(plan.recommendation or {}), "release_gate": "passed" if passed else "failed", "release_reason": regression_reason, "candidate_version": candidate.version, "release_eval_run": run.id}
        plan.save(update_fields=["recommendation", "updated_at"])
    if not passed:
        return
    RagAgentAction.objects.get_or_create(
        owner=candidate.created_by, action_uid=f"publish-config-{candidate.id}",
        defaults={"kb": candidate.kb, "eval_run": run, "action_type": "publish_rag_config", "source": "config_release", "title": f"发布实验配置 v{candidate.version}", "description": "参数实验 Winner 已通过 release suite。确认后发布为知识库活跃配置。", "confirm_label": "确认发布", "payload": {"config_version": candidate.id}, "status": "pending"},
    )
