from django.core.management.base import BaseCommand

from rag.bm25 import bm25_search
from rag.compression import compress_context
from rag.hybrid import rrf_fusion
from rag.models import Chunk, KnowledgeBase
from rag.query_rewrite import rewrite_query
from rag.rerank import rerank_candidates
from rag.services import retrieve


class Command(BaseCommand):
    help = "Inspect the RAG retrieval pipeline for a query."

    def add_arguments(self, parser):
        parser.add_argument("query")
        parser.add_argument("--kb-id", type=int, default=None)
        parser.add_argument("--show-chunks", action="store_true")
        parser.add_argument("--top-k", type=int, default=None)
        parser.add_argument("--bm25-top-k", type=int, default=None)
        parser.add_argument("--rrf-k", type=int, default=None)
        parser.add_argument("--rerank-top-n", type=int, default=None)
        parser.add_argument("--query-rewrite-strategy", default=None)
        parser.add_argument("--compression-strategy", default=None)

    def handle(self, *args, **options):
        kb = self.get_kb(options["kb_id"])
        query = options["query"]
        rewrite_result = rewrite_query(query, options["query_rewrite_strategy"])
        retrieval_query = rewrite_result["rewritten_query"]
        self.stdout.write(f"KB: {kb.id} {kb.name}")
        self.stdout.write(f"Query: {query}")
        self.stdout.write(f"Rewrite: {rewrite_result['rewrite_strategy']} -> {retrieval_query}")
        self.stdout.write(f"Chunks: {Chunk.objects.filter(kb=kb).count()}")

        if options["show_chunks"]:
            self.stdout.write("\n== Indexed Chunks ==")
            for chunk in Chunk.objects.filter(kb=kb).select_related("document").order_by("id"):
                text = chunk.content.replace("\n", " | ")
                self.stdout.write(f"[{chunk.id}] {chunk.document.filename}: {text[:500]}")

        vector_top_k = options["top_k"]
        bm25_top_k = options["bm25_top_k"]
        rerank_top_n = options["rerank_top_n"]
        hybrid_top_k = max(value for value in [vector_top_k, bm25_top_k, rerank_top_n] if value is not None) if any(
            value is not None for value in [vector_top_k, bm25_top_k, rerank_top_n]
        ) else None

        bm25_results = bm25_search(kb, retrieval_query, top_k=bm25_top_k)
        vector_results = retrieve(kb, retrieval_query, top_k=vector_top_k)
        hybrid_results = rrf_fusion(bm25_results, vector_results, top_k=hybrid_top_k, rrf_k=options["rrf_k"])
        rerank_results = rerank_candidates(retrieval_query, hybrid_results, top_n=rerank_top_n, candidate_n=hybrid_top_k)
        compressed_results, compression_stats = compress_context(
            retrieval_query,
            rerank_results,
            strategy=options["compression_strategy"],
        )

        self.print_results("BM25", bm25_results)
        self.print_results("Vector", vector_results)
        self.print_results("Hybrid", hybrid_results)
        self.print_results("Rerank", rerank_results)
        self.print_results("Compression", compressed_results)
        self.stdout.write(f"\nCompression stats: {compression_stats}")

    def get_kb(self, kb_id):
        if kb_id:
            return KnowledgeBase.objects.get(id=kb_id)
        return KnowledgeBase.objects.order_by("-created_at").first()

    def print_results(self, title, results):
        self.stdout.write(f"\n== {title} ==")
        if not results:
            self.stdout.write("(empty)")
            return
        for item in results:
            text = item.get("content", "").replace("\n", " | ")
            extras = []
            if "matched_terms" in item:
                extras.append(f"matched={item['matched_terms']}")
            if "pre_rerank_rank" in item:
                extras.append(f"before={item['pre_rerank_rank']}")
            self.stdout.write(
                f"#{item.get('rank')} chunk={item.get('chunk_id')} score={item.get('score')} "
                f"engine={item.get('engine')} {' '.join(extras)}\n{text[:500]}"
            )
