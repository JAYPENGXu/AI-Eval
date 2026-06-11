from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from rag.bm25 import bm25_search
from rag.compression import compress_context
from rag.hybrid import rrf_fusion
from rag.models import Chunk, KnowledgeBase
from rag.query_rewrite import rewrite_query
from rag.rerank import rerank_candidates
from rag.services import get_openai_client, retrieve


@dataclass
class StageCheck:
    name: str
    best_rank: int | None
    passed: bool


class Command(BaseCommand):
    help = "Run a lightweight RAG evaluation suite against the current knowledge base."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cases",
            default=str(Path(__file__).resolve().parents[2] / "eval_cases.example.json"),
            help="Path to eval cases JSON. Defaults to rag/eval_cases.example.json.",
        )
        parser.add_argument("--kb-id", type=int, default=None, help="KnowledgeBase id. Defaults to latest KB.")
        parser.add_argument("--with-answer", action="store_true", help="Also call the chat model and score answer keywords.")
        parser.add_argument(
            "--compression-strategy",
            default=None,
            help="Override context compression strategy: none, sentence_filter, structure_aware, or llm.",
        )
        parser.add_argument("--top-k", type=int, default=None, help="Override vector search top_k.")
        parser.add_argument("--bm25-top-k", type=int, default=None, help="Override BM25 top_k.")
        parser.add_argument("--rrf-k", type=int, default=None, help="Override RRF k.")
        parser.add_argument("--rerank-top-n", type=int, default=None, help="Override rerank top_n.")
        parser.add_argument("--query-rewrite-strategy", default=None, help="Override query rewrite strategy: none, rule, or llm.")
        parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
        parser.add_argument("--fail-fast", action="store_true", help="Stop at the first failed case.")

    def handle(self, *args, **options):
        cases = self.load_cases(Path(options["cases"]))
        kb = self.get_kb(options["kb_id"])
        if not kb:
            raise CommandError("No knowledge base found. Upload and index a document first.")
        if not Chunk.objects.filter(kb=kb).exists():
            raise CommandError(f"Knowledge base {kb.id} has no indexed chunks.")

        results = []
        for case in cases:
            result = self.run_case(kb, case, options)
            results.append(result)
            if not options["json"]:
                self.print_case(result)
            if options["fail_fast"] and not result["passed"]:
                break

        summary = {
            "kb": {"id": kb.id, "name": kb.name},
            "case_count": len(results),
            "passed_count": sum(1 for item in results if item["passed"]),
            "failed_count": sum(1 for item in results if not item["passed"]),
            "with_answer": options["with_answer"],
        }

        if options["json"]:
            self.stdout.write(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
        else:
            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Summary: {summary['passed_count']}/{summary['case_count']} passed "
                    f"(KB {kb.id}: {kb.name})"
                )
                if summary["failed_count"] == 0
                else self.style.ERROR(
                    f"Summary: {summary['passed_count']}/{summary['case_count']} passed, "
                    f"{summary['failed_count']} failed (KB {kb.id}: {kb.name})"
                )
            )

        if summary["failed_count"]:
            raise SystemExit(1)

    def load_cases(self, path: Path) -> list[dict]:
        if not path.exists():
            raise CommandError(f"Eval cases file not found: {path}")
        with path.open("r", encoding="utf-8") as file:
            cases = json.load(file)
        if not isinstance(cases, list) or not cases:
            raise CommandError("Eval cases JSON must be a non-empty array.")
        return cases

    def get_kb(self, kb_id: int | None) -> KnowledgeBase | None:
        if kb_id:
            return KnowledgeBase.objects.get(id=kb_id)
        return KnowledgeBase.objects.order_by("-created_at").first()

    def run_case(self, kb: KnowledgeBase, case: dict, options: dict) -> dict:
        question = (case.get("question") or "").strip()
        if not question:
            raise CommandError(f"Case {case.get('id') or '<missing id>'} has no question.")

        expected_keywords = case.get("expected_keywords") or []
        expected_chunk_keywords = case.get("expected_chunk_keywords") or expected_keywords
        max_expected_rank = int(case.get("max_expected_rank") or settings.RAG_TOP_K)
        min_context_hit_rate = float(case.get("min_context_keyword_hit_rate") or 1.0)
        min_answer_hit_rate = float(case.get("min_answer_keyword_hit_rate") or 1.0)
        rewrite_result = rewrite_query(question, options["query_rewrite_strategy"])
        retrieval_query = rewrite_result["rewritten_query"]

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
        compressed_context = self.join_context(compressed_results)

        stage_checks = [
            self.check_stage("bm25", bm25_results, expected_chunk_keywords, max_expected_rank),
            self.check_stage("vector", vector_results, expected_chunk_keywords, max_expected_rank),
            self.check_stage("hybrid", hybrid_results, expected_chunk_keywords, max_expected_rank),
            self.check_stage("rerank", rerank_results, expected_chunk_keywords, max_expected_rank),
            self.check_stage("compression", compressed_results, expected_chunk_keywords, max_expected_rank),
        ]

        context_keywords = self.keyword_report(compressed_context, expected_keywords)
        context_passed = context_keywords["hit_rate"] >= min_context_hit_rate

        answer = ""
        answer_keywords = None
        answer_passed = True
        if options["with_answer"]:
            answer = self.answer_question(question, compressed_context)
            answer_keywords = self.keyword_report(answer, expected_keywords)
            answer_passed = answer_keywords["hit_rate"] >= min_answer_hit_rate

        passed = (
            self.get_stage(stage_checks, "hybrid").passed
            and self.get_stage(stage_checks, "rerank").passed
            and self.get_stage(stage_checks, "compression").passed
            and context_passed
            and answer_passed
        )

        return {
            "id": case.get("id") or question[:32],
            "description": case.get("description", ""),
            "question": question,
            "rewritten_query": retrieval_query,
            "rewrite_strategy": rewrite_result["rewrite_strategy"],
            "passed": passed,
            "stage_checks": [check.__dict__ for check in stage_checks],
            "context_keywords": context_keywords,
            "context_passed": context_passed,
            "compression_stats": compression_stats,
            "answer": answer,
            "answer_keywords": answer_keywords,
            "answer_passed": answer_passed,
            "top_chunks": {
                "bm25": self.top_chunk_ids(bm25_results),
                "vector": self.top_chunk_ids(vector_results),
                "hybrid": self.top_chunk_ids(hybrid_results),
                "rerank": self.top_chunk_ids(rerank_results),
                "compression": self.top_chunk_ids(compressed_results),
            },
        }

    def check_stage(self, name: str, results: list[dict], keywords: list[str], max_rank: int) -> StageCheck:
        best_rank = None
        for index, item in enumerate(results, start=1):
            content = item.get("content") or ""
            if self.contains_all(content, keywords):
                best_rank = item.get("rank") or index
                break
        return StageCheck(name=name, best_rank=best_rank, passed=best_rank is not None and best_rank <= max_rank)

    def answer_question(self, question: str, compressed_context: str) -> str:
        prompt = (
            "你是一个严谨的知识库问答助手。"
            "请严格依据参考资料回答用户问题。\n"
            "如果参考资料不足以回答，"
            '请明确说明"当前知识库资料不足以回答"。\n\n'
            f"参考资料：\n{compressed_context}\n\n"
            f"用户问题：{question}\n\n回答："
        )
        completion = get_openai_client().chat.completions.create(
            model=settings.CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return completion.choices[0].message.content or ""

    def join_context(self, sources: list[dict]) -> str:
        return "\n\n---\n\n".join(
            f"source: {source.get('document', '')}\ncontent: {source.get('content', '')}" for source in sources
        )

    def keyword_report(self, text: str, keywords: list[str]) -> dict:
        hits = [keyword for keyword in keywords if self.contains(text, keyword)]
        misses = [keyword for keyword in keywords if not self.contains(text, keyword)]
        total = len(keywords)
        return {
            "expected": keywords,
            "hits": hits,
            "misses": misses,
            "hit_count": len(hits),
            "total": total,
            "hit_rate": round(len(hits) / total, 4) if total else 1.0,
        }

    def contains_all(self, text: str, keywords: list[str]) -> bool:
        return all(self.contains(text, keyword) for keyword in keywords)

    def contains(self, text: str, keyword: str) -> bool:
        return keyword.casefold() in text.casefold()

    def get_stage(self, checks: list[StageCheck], name: str) -> StageCheck:
        return next(check for check in checks if check.name == name)

    def top_chunk_ids(self, results: list[dict], limit: int = 5) -> list[int | None]:
        return [item.get("chunk_id") for item in results[:limit]]

    def print_case(self, result: dict):
        marker = self.style.SUCCESS("PASS") if result["passed"] else self.style.ERROR("FAIL")
        self.stdout.write(f"\n[{marker}] {result['id']}")
        self.stdout.write(f"Question: {result['question']}")
        self.stdout.write(f"Rewrite: {result.get('rewrite_strategy')} -> {result.get('rewritten_query')}")
        for check in result["stage_checks"]:
            rank = check["best_rank"] if check["best_rank"] is not None else "-"
            state = "ok" if check["passed"] else "miss"
            self.stdout.write(f"  {check['name']:<11} rank={rank:<3} {state}")
        keywords = result["context_keywords"]
        self.stdout.write(
            f"  context keywords: {keywords['hit_count']}/{keywords['total']} "
            f"hit_rate={keywords['hit_rate']}"
        )
        if keywords["misses"]:
            self.stdout.write(f"  context missing: {', '.join(keywords['misses'])}")
        stats = result["compression_stats"]
        self.stdout.write(
            "  compression: "
            f"original={stats.get('original_tokens')} compressed={stats.get('compressed_tokens')} "
            f"saved={stats.get('saved_tokens')} ratio={stats.get('saving_ratio')}"
        )
        if result["answer_keywords"] is not None:
            answer_keywords = result["answer_keywords"]
            self.stdout.write(
                f"  answer keywords: {answer_keywords['hit_count']}/{answer_keywords['total']} "
                f"hit_rate={answer_keywords['hit_rate']}"
            )
            if answer_keywords["misses"]:
                self.stdout.write(f"  answer missing: {', '.join(answer_keywords['misses'])}")
