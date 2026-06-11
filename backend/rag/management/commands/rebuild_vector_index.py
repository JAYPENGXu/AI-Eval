from django.core.management.base import BaseCommand

from rag.models import Chunk, Document
from rag.vector_store import get_vector_store


class Command(BaseCommand):
    help = "Rebuild Milvus vector index from chunks stored in Django database."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", type=int, default=None)

    def handle(self, *args, **options):
        store = get_vector_store()
        queryset = Document.objects.all().order_by("id")
        if options["document_id"]:
            queryset = queryset.filter(id=options["document_id"])

        total = 0
        for document in queryset:
            chunks = list(Chunk.objects.filter(document=document).exclude(embedding__isnull=True).order_by("id"))
            store.delete_document(document.id)
            store.index_chunks(chunks)
            total += len(chunks)
            self.stdout.write(f"indexed document={document.id} chunks={len(chunks)}")

        self.stdout.write(self.style.SUCCESS(f"vector index rebuilt chunks={total}"))
