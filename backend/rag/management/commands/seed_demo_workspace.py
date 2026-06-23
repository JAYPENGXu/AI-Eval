from django.core.management.base import BaseCommand

from rag.demo_seed import DEMO_SEED_VERSION, seed_demo_workspace


class Command(BaseCommand):
    help = "Seed the fixed multi-tenant RAGOps demo workspace. Static PDFs are reused."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete the existing demo tenants before seeding.")
        parser.add_argument("--no-process", action="store_true", help="Create data without parsing or indexing documents.")

    def handle(self, *args, **options):
        result = seed_demo_workspace(process=not options["no_process"], reset=options["reset"])
        self.stdout.write(self.style.SUCCESS(
            f"Demo {DEMO_SEED_VERSION} ready: org={result['organization'].slug} kb={result['knowledge_base'].id} documents={len(result['documents'])}"
        ))
