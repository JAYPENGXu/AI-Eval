from django.core.management.base import BaseCommand, CommandError

from rag.models import Chunk
from rag.vector_store import get_vector_store


class Command(BaseCommand):
    help = "Backfill organization/access-policy scalar metadata for existing vector rows."

    def add_arguments(self, parser):
        parser.add_argument("--kb", type=int)

    def handle(self, *args, **options):
        queryset = Chunk.objects.exclude(kb__organization__isnull=True).exclude(access_policy__isnull=True).select_related("kb")
        if options.get("kb"):
            queryset = queryset.filter(kb_id=options["kb"])
        chunks = list(queryset)
        if not chunks:
            self.stdout.write("No authorized chunks to backfill.")
            return
        try:
            get_vector_store().index_chunks(chunks)
        except Exception as exc:
            raise CommandError(f"Authorization metadata backfill failed closed: {exc}") from exc
        self.stdout.write(self.style.SUCCESS(f"Backfilled {len(chunks)} vector rows."))
