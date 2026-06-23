from celery import shared_task
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone
from .document_parsing.service import execute_parse_run


@shared_task(bind=True, name="rag.parse_document", acks_late=True, reject_on_worker_lost=True)
def parse_document_task(self, run_id):
    execute_parse_run(run_id, task_id=str(self.request.id or ""))


@shared_task(bind=True, name="rag.index_document", acks_late=True, reject_on_worker_lost=True, max_retries=2)
def index_document_task(self, run_id):
    from .indexing import index_document
    from .models import DocumentIndexRun
    with transaction.atomic():
        run=DocumentIndexRun.objects.select_for_update().select_related("document","parse_run").get(id=run_id)
        task_id=str(self.request.id or "")
        if run.status=="completed" or (run.status=="running" and run.celery_task_id and run.celery_task_id != task_id): return
        if run.status not in {"queued","running"}: return
        run.status="running"; run.celery_task_id=task_id; run.started_at=run.started_at or timezone.now(); run.heartbeat_at=timezone.now(); run.error_message=""
        run.save(update_fields=["status","celery_task_id","started_at","heartbeat_at","error_message","updated_at"])
    try:
        count=index_document(run.document,run.chunk_method,run.chunk_options,run.parse_run_id)
        run.refresh_from_db()
        run.status="completed"; run.chunk_count=count; run.progress_current=count; run.progress_total=count; run.finished_at=timezone.now(); run.heartbeat_at=timezone.now()
        run.save(update_fields=["status","chunk_count","progress_current","progress_total","finished_at","heartbeat_at","updated_at"])
        run.document.index_signature=run.target_signature; run.document.index_manifest=run.target_manifest; run.document.indexed_at=timezone.now()
        run.document.save(update_fields=["index_signature","index_manifest","indexed_at","updated_at"])
    except Exception as exc:
        retries = int(self.request.retries or 0)
        if retries < self.max_retries:
            DocumentIndexRun.objects.filter(id=run_id).update(
                status="queued", error_message=str(exc), retry_count=retries + 1,
                heartbeat_at=timezone.now(), finished_at=None,
            )
            raise self.retry(exc=exc, countdown=2 ** retries)
        DocumentIndexRun.objects.filter(id=run_id).update(
            status="failed", error_message=str(exc), finished_at=timezone.now(), retry_count=retries
        )
        raise


@shared_task(bind=True, name="rag.run_eval", acks_late=True, reject_on_worker_lost=True)
def run_eval_task(self, run_id, options):
    from .models import RagEvalRun
    task_id=str(self.request.id or "")
    with transaction.atomic():
        run = RagEvalRun.objects.select_for_update().get(id=run_id)
        if run.status == "completed" or (run.status == "running" and run.celery_task_id and run.celery_task_id != task_id):
            return
        if run.status not in {"queued", "running"}:
            return
        run.status = "running"; run.celery_task_id = task_id; run.heartbeat_at = timezone.now()
        run.started_at = run.started_at or timezone.now(); run.error_message = ""
        run.save(update_fields=["status", "celery_task_id", "heartbeat_at", "started_at", "error_message"])
    try: call_command("eval_ragas",run_id=run_id,**options)
    except Exception as exc:
        RagEvalRun.objects.filter(id=run_id).update(status="failed",error_message=str(exc),finished_at=timezone.now())
        raise
    finally:
        plan_id=(RagEvalRun.objects.filter(id=run_id).values_list("settings",flat=True).first() or {}).get("experiment_plan")
        if plan_id: finalize_experiment_plan_task.apply_async(args=[plan_id],countdown=1,queue="orchestration")


@shared_task(bind=True, name="rag.session_summary", acks_late=True, reject_on_worker_lost=True)
def session_summary_task(self, session_id):
    from .models import ChatSessionSummary
    from .session_memory import run_session_summary_update
    ChatSessionSummary.objects.filter(session_id=session_id,status__in=["queued","running"]).update(status="running",celery_task_id=str(self.request.id or ""),last_started_at=timezone.now())
    run_session_summary_update(session_id)


@shared_task(bind=True, name="rag.finalize_experiment", acks_late=True)
def finalize_experiment_plan_task(self, plan_id):
    from .experiments import refresh_experiment_plan
    from .models import RagExperimentPlan
    plan=RagExperimentPlan.objects.filter(id=plan_id).first()
    if plan: refresh_experiment_plan(plan)


@shared_task(bind=True, name="rag.parse_eval", acks_late=True, reject_on_worker_lost=True)
def parse_eval_run_task(self, run_id):
    from .models import DocumentParseEvalRun
    from .parse_evaluation import execute_parse_eval_run
    DocumentParseEvalRun.objects.filter(id=run_id,status="queued").update(celery_task_id=str(self.request.id or ""))
    execute_parse_eval_run(run_id)
@shared_task(name="rag.reset_demo_runtime")
def reset_demo_runtime_task():
    from django.conf import settings
    from .demo_reset import reset_demo_runtime

    if not settings.DEMO_MODE:
        return {"skipped": True, "reason": "demo_mode_disabled"}
    return reset_demo_runtime()
