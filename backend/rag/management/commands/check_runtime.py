import json
from django.core.management.base import BaseCommand, CommandError
from rag.health import health_report

class Command(BaseCommand):
    help = "Check database, Redis, Celery, media and vector-store readiness."
    def handle(self, *args, **options):
        report = health_report(detailed=True)
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        if not report["ready"]:
            raise CommandError("Runtime dependencies are not ready.")
        self.stdout.write(self.style.SUCCESS("Runtime is ready."))
