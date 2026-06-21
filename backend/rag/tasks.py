from celery import shared_task

from .document_parsing.service import execute_parse_run


@shared_task(bind=True, name="rag.parse_document", acks_late=True, reject_on_worker_lost=True)
def parse_document_task(self, run_id: int) -> None:
    execute_parse_run(run_id, task_id=str(self.request.id or ""))
