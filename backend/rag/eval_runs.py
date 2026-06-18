from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import RagEvalRun

logger = logging.getLogger(__name__)

STALE_EVAL_ERROR_MESSAGE = (
    "评测任务超时或后台 worker 已中断，已自动标记为失败。请重新运行评测。"
)


def eval_run_stale_cutoff():
    timeout_seconds = max(60, int(getattr(settings, "EVAL_RUN_STALE_TIMEOUT_SECONDS", 3600)))
    return timezone.now() - timedelta(seconds=timeout_seconds)


def is_stale_eval_run(run: RagEvalRun, *, cutoff=None) -> bool:
    if run.status != "running" or run.finished_at:
        return False
    started_at = run.started_at or run.created_at
    if not started_at:
        return False
    return started_at < (cutoff or eval_run_stale_cutoff())


def reconcile_stale_eval_runs(*, owner=None, kb_id=None) -> int:
    cutoff = eval_run_stale_cutoff()
    queryset = RagEvalRun.objects.filter(
        status="running",
        finished_at__isnull=True,
        started_at__lt=cutoff,
    )
    if owner is not None:
        queryset = queryset.filter(kb__owner=owner)
    if kb_id is not None:
        queryset = queryset.filter(kb_id=kb_id)
    updated = queryset.update(
        status="failed",
        error_message=STALE_EVAL_ERROR_MESSAGE,
        finished_at=timezone.now(),
    )
    if updated:
        logger.info("marked stale eval runs count=%s owner=%s kb=%s", updated, getattr(owner, "id", owner), kb_id)
    return updated


def reconcile_stale_eval_run(run: RagEvalRun) -> RagEvalRun:
    if not is_stale_eval_run(run):
        return run
    updated = RagEvalRun.objects.filter(id=run.id, status="running", finished_at__isnull=True).update(
        status="failed",
        error_message=STALE_EVAL_ERROR_MESSAGE,
        finished_at=timezone.now(),
    )
    if updated:
        logger.info("marked stale eval run id=%s", run.id)
        run.refresh_from_db()
    return run
