from __future__ import annotations

import json
import math
import re
import time
import asyncio
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from rag.bm25 import bm25_search
from rag.compression import compress_context
from rag.hybrid import rrf_fusion
from rag.models import Chunk, KnowledgeBase, RagBenchmarkCase, RagEvalCaseResult, RagEvalRun
from rag.query_rewrite import rewrite_query
from rag.query_router import classify_query_route
from rag.rerank import rerank_candidates
from rag.services import get_openai_client, retrieve


DEFAULT_METRICS = "faithfulness,answer_relevancy,context_precision,context_recall"
REFERENCE_STOP_TERMS = {
    "参考答案", "标准答案", "这个问题", "当前资料", "知识库",
    "可以回答", "包括", "以及", "使用", "工具", "阶段",
}
DIAGNOSTIC_HIT_MIN_TERMS = 1
DIAGNOSTIC_HIT_MIN_COVERAGE = 0.2
FINAL_ANSWER_MIN_COVERAGE = 0.5
FINAL_ANSWER_MIN_SCORE = 0.6


class Command(BaseCommand):
    help = "Run RAGAS evaluation against the current RAG pipeline."

    def add_arguments(self, parser):
        parser.add_argument(
            "--cases",
            default=str(Path(__file__).resolve().parents[2] / "eval_cases.example.json"),
            help="Path to eval cases JSON. Defaults to rag/eval_cases.example.json.",
        )
        parser.add_argument("--kb-id", type=int, default=None, help="KnowledgeBase id. Defaults to latest KB.")
        parser.add_argument("--metrics", default=DEFAULT_METRICS, help=f"Comma-separated metrics. Default: {DEFAULT_METRICS}.")
        parser.add_argument("--top-k", type=int, default=None, help="Override vector search top_k.")
        parser.add_argument("--bm25-top-k", type=int, default=None, help="Override BM25 top_k.")
        parser.add_argument("--rrf-k", type=int, default=None, help="Override RRF k.")
        parser.add_argument("--rerank-top-n", type=int, default=None, help="Override rerank top_n.")
        parser.add_argument("--query-rewrite-strategy", default=None, help="Override query rewrite strategy: none, rule, or llm.")
        parser.add_argument(
            "--compression-strategy",
            default=None,
            help="Override context compression strategy: none, sentence_filter, structure_aware, or llm.",
        )
        parser.add_argument("--suite", default=None, help="Run only enabled benchmark cases in a suite: smoke, benchmark, regression, or release.")
        parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N cases.")
        parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
        parser.add_argument("--output", default=None, help="Optional path to save JSON results.")
        parser.add_argument("--no-save", action="store_true", help="Do not save this run to SQLite.")
        parser.add_argument("--run-id", type=int, default=None, help="Update an existing RagEvalRun instead of creating one.")

    def handle(self, *args, **options):
        ragas_runtime = self.load_ragas_runtime()
        kb = self.get_kb(options["kb_id"])
        if not kb:
            raise CommandError("No knowledge base found. Upload and index a document first.")
        if not Chunk.objects.filter(kb=kb).exists():
            raise CommandError(f"Knowledge base {kb.id} has no indexed chunks.")
        cases, case_source = self.load_cases(kb, Path(options["cases"]), options.get("suite"))
        if options["limit"]:
            cases = cases[: options["limit"]]

        requested_metrics = self.parse_metrics(options["metrics"])
        metrics = self.build_metrics(ragas_runtime, requested_metrics)
        if not metrics:
            raise CommandError("No supported RAGAS metrics selected.")
        metric_names = [self.metric_name(metric) for metric in metrics]
        eval_settings = self.build_eval_settings(options, metric_names, case_source)
        eval_run = None
        if not options["no_save"]:
            if options["run_id"]:
                eval_run = RagEvalRun.objects.get(id=options["run_id"], kb=kb)
                eval_run.case_results.all().delete()
                eval_run.status = "running"
                eval_run.metrics = metric_names
                eval_run.settings = eval_settings
                eval_run.mean_scores = {}
                eval_run.retrieval_metrics = {}
                eval_run.case_count = len(cases)
                eval_run.cases_path = str(Path(options["cases"]).resolve())
                eval_run.error_message = ""
                eval_run.started_at = timezone.now()
                eval_run.finished_at = None
                eval_run.save(
                    update_fields=[
                        "status",
                        "metrics",
                        "settings",
                        "mean_scores",
                        "retrieval_metrics",
                        "case_count",
                        "cases_path",
                        "error_message",
                        "started_at",
                        "finished_at",
                    ]
                )
            else:
                eval_run = RagEvalRun.objects.create(
                    kb=kb,
                    status="running",
                    metrics=metric_names,
                    settings=eval_settings,
                    case_count=len(cases),
                    cases_path=str(Path(options["cases"]).resolve()),
                )

        dataset_rows = []
        pipeline_results = []
        try:
            for case in cases:
                pipeline_result = self.run_pipeline(kb, case, options)
                pipeline_results.append(pipeline_result)
                dataset_rows.append(
                    {
                        "question": pipeline_result["question"],
                        "answer": pipeline_result["answer"],
                        "contexts": pipeline_result["contexts"],
                        "ground_truth": pipeline_result["reference"],
                    }
                )
                if not options["json"]:
                    self.stdout.write(
                        f"Prepared {pipeline_result['id']}: "
                        f"{len(pipeline_result['contexts'])} contexts, "
                        f"rewrite={pipeline_result['rewrite_strategy']}"
                    )

            dataset = ragas_runtime["Dataset"].from_list(dataset_rows)
            llm = self.create_ragas_llm(ragas_runtime)
            embeddings = self.create_ragas_embeddings(ragas_runtime)
            ragas_result = ragas_runtime["evaluate"](
                dataset,
                metrics=metrics,
                llm=llm,
                embeddings=embeddings,
            )
            score_rows = self.to_score_rows(ragas_result)

            results = []
            for pipeline_result, score_row in zip(pipeline_results, score_rows):
                scores = {name: self.safe_float(score_row.get(name)) for name in metric_names if name in score_row}
                pipeline_result["diagnostics"]["final_answer"] = self.build_final_answer_diagnostic(
                    pipeline_result["answer"],
                    pipeline_result["reference"],
                    scores,
                )
                enriched_result = {**pipeline_result, "scores": scores}
                enriched_result["deterministic_results"] = self.score_deterministic(enriched_result)
                enriched_result["judge_results"] = self.score_with_llm_judge(enriched_result)
                results.append(enriched_result)

            summary = {
                "kb": {"id": kb.id, "name": kb.name},
                "case_count": len(results),
                "metrics": metric_names,
                "mean_scores": self.mean_scores(results, metric_names),
                "retrieval_metrics": self.aggregate_retrieval_metrics(results),
                "deterministic": self.aggregate_deterministic_results(results),
                "judge": self.aggregate_judge_results(results),
                "eval_run_id": eval_run.id if eval_run else None,
            }
            payload = {"summary": summary, "results": results}
            if eval_run:
                self.save_eval_results(eval_run, results, summary)
        except Exception as exc:
            if eval_run:
                eval_run.status = "failed"
                eval_run.error_message = str(exc)
                eval_run.finished_at = timezone.now()
                eval_run.save(update_fields=["status", "error_message", "finished_at"])
            raise

        if options["output"]:
            output_path = Path(options["output"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.print_results(payload)

    def load_ragas_runtime(self) -> dict[str, Any]:
        try:
            from datasets import Dataset
            from langchain_core.embeddings import Embeddings
            from langchain_openai import ChatOpenAI
            from ragas import evaluate
            from ragas import metrics as ragas_metrics
        except ImportError as exc:
            raise CommandError(
                "Missing RAGAS dependencies. Install backend requirements first:\n"
                "  source venv/bin/activate\n"
                "  pip install -r requirements.txt\n"
                f"Original import error: {exc}"
            ) from exc
        return {
            "Dataset": Dataset,
            "ChatOpenAI": ChatOpenAI,
            "Embeddings": Embeddings,
            "evaluate": evaluate,
            "metrics_module": ragas_metrics,
        }

    def load_cases(self, kb: KnowledgeBase, path: Path, suite: str | None = None) -> tuple[list[dict], str]:
        queryset = RagBenchmarkCase.objects.filter(kb=kb, enabled=True)
        if suite:
            allowed_suites = {choice[0] for choice in RagBenchmarkCase.SUITE_CHOICES}
            if suite not in allowed_suites:
                raise CommandError(f"Unsupported benchmark suite: {suite}. Expected one of: {', '.join(sorted(allowed_suites))}.")
            queryset = queryset.filter(suite=suite)
        benchmark_cases = list(queryset.order_by("case_id", "id"))
        if benchmark_cases:
            return [
                {
                    "id": item.case_id,
                    "question": item.question,
                    "reference": item.reference,
                    "case_type": item.case_type,
                    "tags": item.tags,
                    "expected_terms": item.expected_terms,
                    "target_chunk_ids": item.target_chunk_ids,
                    "suite": item.suite,
                    "deterministic_checks": item.deterministic_checks,
                    "rubric": item.rubric,
                    "thresholds": item.thresholds,
                    "source": item.source,
                    "notes": item.notes,
                    "difficulty": item.difficulty,
                }
                for item in benchmark_cases
            ], f"database_{suite or 'all'}"

        if not path.exists():
            raise CommandError(f"Eval cases file not found: {path}")
        with path.open("r", encoding="utf-8") as file:
            cases = json.load(file)
        if not isinstance(cases, list) or not cases:
            raise CommandError("Eval cases JSON must be a non-empty array.")
        for case in cases:
            if not (case.get("reference") or case.get("ground_truth") or case.get("expected_answer")):
                raise CommandError(f"Case {case.get('id') or case.get('question')} has no reference answer.")
            case.setdefault("case_type", "expert")
            case.setdefault("suite", suite or "benchmark")
            case.setdefault("deterministic_checks", {})
            case.setdefault("rubric", {})
            case.setdefault("thresholds", {})
        return cases, "json_fallback"

    def get_kb(self, kb_id: int | None) -> KnowledgeBase | None:
        if kb_id:
            return KnowledgeBase.objects.get(id=kb_id)
        return KnowledgeBase.objects.order_by("-created_at").first()

    def parse_metrics(self, raw_metrics: str) -> list[str]:
        return [metric.strip() for metric in raw_metrics.split(",") if metric.strip()]

    def build_eval_settings(self, options: dict, metric_names: list[str], case_source: str) -> dict:
        return {
            "metrics": metric_names,
            "case_source": case_source,
            "suite": options.get("suite") or "all",
            "top_k": options["top_k"] or settings.RAG_TOP_K,
            "bm25_top_k": options["bm25_top_k"] or settings.BM25_TOP_K,
            "hybrid_top_k": max(
                options["top_k"] or settings.RAG_TOP_K,
                options["bm25_top_k"] or settings.BM25_TOP_K,
                options["rerank_top_n"] or settings.RERANK_TOP_N,
                settings.HYBRID_TOP_K,
            ),
            "rrf_k": options["rrf_k"] or settings.RRF_K,
            "rerank_top_n": options["rerank_top_n"] or settings.RERANK_TOP_N,
            "query_rewrite_strategy": options["query_rewrite_strategy"] or settings.QUERY_REWRITE_STRATEGY,
            "compression_strategy": options["compression_strategy"] or settings.CONTEXT_COMPRESSION_STRATEGY,
            "chat_model": settings.CHAT_MODEL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
        }

    def build_metrics(self, runtime: dict[str, Any], metric_names: list[str]) -> list[Any]:
        module = runtime["metrics_module"]
        metric_aliases = {
            "faithfulness": ["faithfulness"],
            "answer_relevancy": ["answer_relevancy", "response_relevancy"],
            "context_precision": ["context_precision"],
            "context_recall": ["context_recall"],
        }
        metrics = []
        for metric_name in metric_names:
            candidates = metric_aliases.get(metric_name, [metric_name])
            metric = next((getattr(module, candidate) for candidate in candidates if hasattr(module, candidate)), None)
            if metric is None:
                raise CommandError(f"Unsupported or unavailable RAGAS metric: {metric_name}")
            metrics.append(metric)
        return metrics

    def create_ragas_llm(self, runtime: dict[str, Any]) -> Any:
        return runtime["ChatOpenAI"](
            model=settings.CHAT_MODEL,
            api_key=settings.API_KEY,
            base_url=settings.API_BASE,
            temperature=0,
        )

    def create_ragas_embeddings(self, runtime: dict[str, Any]) -> Any:
        base_class = runtime["Embeddings"]

        class CompatibleEmbeddings(base_class):
            def __init__(self):
                self.client = get_openai_client()

            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                cleaned = [self.clean_text(text) for text in texts]
                embeddings = []
                batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)
                for start in range(0, len(cleaned), batch_size):
                    batch = cleaned[start : start + batch_size]
                    response = self.client.embeddings.create(
                        model=settings.EMBEDDING_MODEL,
                        input=batch,
                        dimensions=settings.EMBEDDING_DIMENSIONS,
                    )
                    embeddings.extend(item.embedding for item in response.data)
                return embeddings

            def embed_query(self, text: str) -> list[float]:
                return self.embed_documents([self.clean_text(text)])[0]

            async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
                return await asyncio.to_thread(self.embed_documents, texts)

            async def aembed_query(self, text: str) -> list[float]:
                return await asyncio.to_thread(self.embed_query, text)

            def clean_text(self, text: Any) -> str:
                if isinstance(text, list):
                    text = " ".join(self.clean_text(item) for item in text)
                value = str(text or "").strip()
                return value or " "

        return CompatibleEmbeddings()

    def run_pipeline(self, kb: KnowledgeBase, case: dict, options: dict) -> dict:
        question = (case.get("question") or "").strip()
        if not question:
            raise CommandError(f"Case {case.get('id') or '<missing id>'} has no question.")

        started_at = time.monotonic()
        rewrite_result = rewrite_query(question, options["query_rewrite_strategy"])
        retrieval_query = rewrite_result["rewritten_query"]
        route_decision = classify_query_route(question, retrieval_query).as_dict()
        vector_top_k = options["top_k"]
        bm25_top_k = options["bm25_top_k"]
        rerank_top_n = options["rerank_top_n"]
        hybrid_top_k = (
            max(value for value in [vector_top_k, bm25_top_k, rerank_top_n] if value is not None)
            if any(value is not None for value in [vector_top_k, bm25_top_k, rerank_top_n])
            else None
        )

        bm25_results = bm25_search(kb, retrieval_query, top_k=bm25_top_k)
        vector_results = retrieve(kb, retrieval_query, top_k=vector_top_k)
        hybrid_results = rrf_fusion(bm25_results, vector_results, top_k=hybrid_top_k, rrf_k=options["rrf_k"])
        rerank_results = rerank_candidates(retrieval_query, hybrid_results, top_n=rerank_top_n, candidate_n=hybrid_top_k)
        compressed_results, compression_stats = compress_context(
            retrieval_query,
            rerank_results,
            strategy=options["compression_strategy"],
        )
        contexts = [source.get("content") or "" for source in compressed_results if source.get("content")]
        compressed_context = self.join_context(compressed_results)
        answer = self.answer_question(question, compressed_context)
        latency_ms = round((time.monotonic() - started_at) * 1000)
        reference = case.get("reference") or case.get("ground_truth") or case.get("expected_answer")
        expected_terms = self.normalize_expected_terms(case.get("expected_terms")) or self.extract_reference_terms(reference)
        target_chunk_ids = self.normalize_chunk_ids(case.get("target_chunk_ids"))
        diagnostics = self.build_diagnostics(
            reference=reference,
            answer=answer,
            expected_terms=expected_terms,
            target_chunk_ids=target_chunk_ids,
            vector_results=vector_results,
            bm25_results=bm25_results,
            hybrid_results=hybrid_results,
            rerank_results=rerank_results,
            compressed_results=compressed_results,
        )

        return {
            "id": case.get("id") or question[:32],
            "question": question,
            "reference": reference,
            "case_type": case.get("case_type") or "",
            "suite": case.get("suite") or "",
            "deterministic_checks": case.get("deterministic_checks") or {},
            "rubric": case.get("rubric") or {},
            "thresholds": case.get("thresholds") or {},
            "rewritten_query": retrieval_query,
            "rewrite_strategy": rewrite_result["rewrite_strategy"],
            "answer": answer,
            "contexts": contexts,
            "context_count": len(contexts),
            "expected_terms": expected_terms,
            "target_chunk_ids": target_chunk_ids,
            "diagnostics": diagnostics,
            "router": route_decision,
            "latency_ms": latency_ms,
            "estimated_total_tokens": self.estimate_total_tokens(question, compressed_context, answer),
            "compression_stats": compression_stats,
            "top_chunks": {
                "bm25": self.top_chunk_ids(bm25_results),
                "vector": self.top_chunk_ids(vector_results),
                "hybrid": self.top_chunk_ids(hybrid_results),
                "rerank": self.top_chunk_ids(rerank_results),
                "compression": self.top_chunk_ids(compressed_results),
            },
        }

    def build_diagnostics(
        self,
        *,
        reference: str,
        answer: str,
        expected_terms: list[str],
        target_chunk_ids: list[int],
        vector_results: list[dict],
        bm25_results: list[dict],
        hybrid_results: list[dict],
        rerank_results: list[dict],
        compressed_results: list[dict],
    ) -> dict:
        reference_terms = expected_terms or self.extract_reference_terms(reference)
        return {
            "reference_terms": reference_terms,
            "expected_terms": reference_terms,
            "target_chunk_ids": target_chunk_ids,
            "stages": {
                "vector": self.stage_hit_diagnostic("Vector TopK", vector_results, reference_terms, target_chunk_ids),
                "bm25": self.stage_hit_diagnostic("BM25 TopK", bm25_results, reference_terms, target_chunk_ids),
                "hybrid": self.stage_hit_diagnostic("Hybrid TopK", hybrid_results, reference_terms, target_chunk_ids),
                "rerank": self.stage_hit_diagnostic("Rerank TopN", rerank_results, reference_terms, target_chunk_ids),
                "compression": self.stage_hit_diagnostic("Compression", compressed_results, reference_terms, target_chunk_ids),
            },
            "final_answer": self.build_final_answer_diagnostic(answer, reference, {}),
        }

    def normalize_expected_terms(self, value: Any) -> list[str]:
        if isinstance(value, str):
            raw_terms = [item.strip() for item in value.replace("\n", ",").split(",")]
        else:
            raw_terms = value or []
        terms = []
        seen = set()
        for item in raw_terms:
            term = str(item or "").strip()
            key = term.lower()
            if not term or key in seen:
                continue
            seen.add(key)
            terms.append(key if re.match(r"^[A-Za-z0-9_\-]+$", term) else term)
        return terms[:30]

    def normalize_chunk_ids(self, value: Any) -> list[int]:
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.replace("\n", ",").split(",")]
        else:
            raw_items = value or []
        chunk_ids = []
        for item in raw_items:
            try:
                chunk_ids.append(int(item))
            except (TypeError, ValueError):
                continue
        return sorted(set(chunk_ids))

    def extract_reference_terms(self, reference: str) -> list[str]:
        text = str(reference or "")
        terms = []
        for term in re.findall(r"[A-Za-z0-9_][A-Za-z0-9_\\-]{1,}", text):
            terms.append(term.lower())
        for term in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            cleaned = term.strip()
            if cleaned and cleaned not in REFERENCE_STOP_TERMS:
                terms.append(cleaned)
        deduped = []
        seen = set()
        for term in terms:
            if term in seen:
                continue
            seen.add(term)
            deduped.append(term)
        return deduped[:20]

    def stage_hit_diagnostic(
        self,
        label: str,
        results: list[dict],
        reference_terms: list[str],
        target_chunk_ids: list[int],
    ) -> dict:
        target_ids = set(target_chunk_ids or [])
        matched_terms = set()
        matched_chunks = []
        best_evidence = None
        first_target_rank = None
        matched_target_ids = []
        for fallback_rank, item in enumerate(results, start=1):
            content = str(item.get("content") or "")
            rank = int(item.get("rank") or fallback_rank)
            chunk_id = item.get("chunk_id")
            try:
                normalized_chunk_id = int(chunk_id) if chunk_id is not None else None
            except (TypeError, ValueError):
                normalized_chunk_id = None
            item_terms = self.match_terms(content, reference_terms)
            target_matched = normalized_chunk_id in target_ids if normalized_chunk_id is not None else False
            if target_matched:
                matched_target_ids.append(normalized_chunk_id)
                first_target_rank = rank if first_target_rank is None else min(first_target_rank, rank)
            if item_terms:
                matched_terms.update(item_terms)
                matched_chunks.append(chunk_id)
            if best_evidence is None and (item_terms or target_matched):
                best_evidence = {
                    "chunk_id": chunk_id,
                    "rank": rank,
                    "document": item.get("document"),
                    "matched_terms": item_terms[:8],
                    "target_matched": target_matched,
                    "snippet": self.snippet(content, item_terms[0]) if item_terms else content[:140].strip(),
                }
        term_coverage = len(matched_terms) / len(reference_terms) if reference_terms else 0
        target_recall = len(set(matched_target_ids)) / len(target_ids) if target_ids else None
        term_hit = bool(reference_terms) and (
            len(matched_terms) >= DIAGNOSTIC_HIT_MIN_TERMS
            and term_coverage >= DIAGNOSTIC_HIT_MIN_COVERAGE
        )
        target_hit = bool(target_ids) and bool(matched_target_ids)
        hit = target_hit if target_ids else term_hit
        reciprocal_rank = round(1 / first_target_rank, 4) if first_target_rank else 0
        return {
            "label": label,
            "hit": hit,
            "term_hit": term_hit,
            "target_hit": target_hit,
            "coverage": round(term_coverage, 4),
            "target_recall": round(target_recall, 4) if target_recall is not None else None,
            "rank": first_target_rank,
            "reciprocal_rank": reciprocal_rank,
            "matched_terms": sorted(matched_terms),
            "matched_chunk_ids": [chunk_id for chunk_id in matched_chunks if chunk_id is not None],
            "matched_target_chunk_ids": sorted(set(matched_target_ids)),
            "target_chunk_ids": sorted(target_ids),
            "candidate_count": len(results),
            "evidence": best_evidence,
        }

    def estimate_total_tokens(self, *parts: str) -> int:
        text = "\n".join(str(part or "") for part in parts)
        ascii_words = re.findall(r"[A-Za-z0-9_][A-Za-z0-9_\-]*", text)
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
        other_chars = max(len(text) - sum(len(word) for word in ascii_words) - len(cjk_chars), 0)
        return len(ascii_words) + len(cjk_chars) + math.ceil(other_chars / 4)

    def normalize_check_terms(self, value: Any) -> list[str]:
        if value in (None, False, ""):
            return []
        if value is True:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.replace("\n", ",").split(",")]
        else:
            raw_items = value if isinstance(value, list) else [value]
        return [str(item).strip() for item in raw_items if str(item or "").strip()]

    def contains_all(self, text: str, terms: list[str]) -> tuple[bool, list[str], list[str]]:
        normalized = str(text or "").lower()
        passed = []
        failed = []
        for term in terms:
            if str(term).lower() in normalized:
                passed.append(term)
            else:
                failed.append(term)
        return not failed, passed, failed

    def contains_none(self, text: str, terms: list[str]) -> tuple[bool, list[str]]:
        normalized = str(text or "").lower()
        found = [term for term in terms if str(term).lower() in normalized]
        return not found, found

    def check_stage_hit(self, result: dict, stage: str) -> bool:
        return bool(result.get("diagnostics", {}).get("stages", {}).get(stage, {}).get("hit"))

    def add_check_result(self, rows: list[dict], key: str, passed: bool, expected: Any, actual: Any, detail: str = ""):
        rows.append({
            "key": key,
            "passed": bool(passed),
            "expected": expected,
            "actual": actual,
            "detail": detail,
        })

    def score_deterministic(self, result: dict) -> dict:
        checks = result.get("deterministic_checks") or {}
        thresholds = result.get("thresholds") or {}
        rows = []
        if not isinstance(checks, dict):
            checks = {}

        if "router_intent" in checks:
            actual = result.get("router", {}).get("query_intent")
            self.add_check_result(rows, "router_intent", actual == checks.get("router_intent"), checks.get("router_intent"), actual)

        if "rewrite_contains" in checks:
            terms = self.normalize_check_terms(checks.get("rewrite_contains"))
            passed, matched, missing = self.contains_all(result.get("rewritten_query", ""), terms)
            self.add_check_result(rows, "rewrite_contains", passed, terms, {"matched": matched, "missing": missing})

        if "answer_contains" in checks:
            terms = self.normalize_check_terms(checks.get("answer_contains"))
            passed, matched, missing = self.contains_all(result.get("answer", ""), terms)
            self.add_check_result(rows, "answer_contains", passed, terms, {"matched": matched, "missing": missing})

        if "answer_not_contains" in checks:
            terms = self.normalize_check_terms(checks.get("answer_not_contains"))
            passed, found = self.contains_none(result.get("answer", ""), terms)
            self.add_check_result(rows, "answer_not_contains", passed, terms, {"found": found})

        if checks.get("citation_required"):
            answer = result.get("answer", "")
            citation_found = bool(re.search(r"(\[[^\]]+\]|来源|出处|source|chunk|文档)", answer, re.IGNORECASE))
            self.add_check_result(rows, "citation_required", citation_found, True, citation_found)

        for key, stage in [("vector_hit", "vector"), ("bm25_hit", "bm25"), ("hybrid_hit", "hybrid")]:
            if key in checks:
                actual = self.check_stage_hit(result, stage)
                self.add_check_result(rows, key, actual == bool(checks.get(key)), bool(checks.get(key)), actual)

        if "rerank_keep" in checks:
            actual = self.check_stage_hit(result, "rerank")
            self.add_check_result(rows, "rerank_keep", actual == bool(checks.get("rerank_keep")), bool(checks.get("rerank_keep")), actual)

        if "compression_keep_terms" in checks:
            expected_terms = self.normalize_check_terms(checks.get("compression_keep_terms")) or result.get("expected_terms", [])
            compression_text = "\n".join(result.get("contexts") or [])
            passed, matched, missing = self.contains_all(compression_text, expected_terms)
            self.add_check_result(rows, "compression_keep_terms", passed, expected_terms, {"matched": matched, "missing": missing})

        max_total_tokens = checks.get("max_total_tokens", thresholds.get("max_total_tokens"))
        if max_total_tokens not in (None, ""):
            try:
                expected = int(max_total_tokens)
                actual = int(result.get("estimated_total_tokens") or 0)
                self.add_check_result(rows, "max_total_tokens", actual <= expected, expected, actual)
            except (TypeError, ValueError):
                self.add_check_result(rows, "max_total_tokens", False, max_total_tokens, "invalid threshold")

        max_latency_ms = checks.get("max_latency_ms", thresholds.get("max_latency_ms"))
        if max_latency_ms not in (None, ""):
            try:
                expected = int(max_latency_ms)
                actual = int(result.get("latency_ms") or 0)
                self.add_check_result(rows, "max_latency_ms", actual <= expected, expected, actual)
            except (TypeError, ValueError):
                self.add_check_result(rows, "max_latency_ms", False, max_latency_ms, "invalid threshold")

        total = len(rows)
        passed_count = sum(1 for row in rows if row.get("passed"))
        pass_rate = round(passed_count / total, 4) if total else None
        min_pass_rate = thresholds.get("deterministic_min_pass_rate", 1) if isinstance(thresholds, dict) else 1
        try:
            min_pass_rate = float(min_pass_rate)
        except (TypeError, ValueError):
            min_pass_rate = 1
        overall_passed = True if total == 0 else pass_rate >= min_pass_rate
        return {
            "passed": overall_passed,
            "pass_rate": pass_rate,
            "passed_count": passed_count,
            "failed_count": total - passed_count,
            "total_count": total,
            "min_pass_rate": min_pass_rate,
            "checks": rows,
        }

    def aggregate_deterministic_results(self, results: list[dict]) -> dict:
        scored = [item.get("deterministic_results") or {} for item in results if item.get("deterministic_results", {}).get("total_count") is not None]
        with_checks = [item for item in scored if item.get("total_count", 0) > 0]
        if not with_checks:
            return {"case_count": 0, "pass_rate": None, "failed_count": 0}
        passed_count = sum(1 for item in with_checks if item.get("passed"))
        return {
            "case_count": len(with_checks),
            "passed_count": passed_count,
            "failed_count": len(with_checks) - passed_count,
            "pass_rate": round(passed_count / len(with_checks), 4),
        }

    def build_final_answer_diagnostic(self, answer: str, reference: str, scores: dict) -> dict:
        reference_terms = self.extract_reference_terms(reference)
        matched_terms = self.match_terms(answer, reference_terms)
        coverage = len(set(matched_terms)) / len(reference_terms) if reference_terms else 0
        scored_values = [
            value
            for key, value in scores.items()
            if key in {"answer_relevancy", "faithfulness", "context_recall"} and value is not None
        ]
        score_gate = min(scored_values) >= FINAL_ANSWER_MIN_SCORE if scored_values else True
        correct = bool(reference_terms) and coverage >= FINAL_ANSWER_MIN_COVERAGE and score_gate
        return {
            "correct": correct,
            "coverage": round(coverage, 4),
            "matched_terms": sorted(set(matched_terms)),
            "score_gate": score_gate,
            "score_threshold": FINAL_ANSWER_MIN_SCORE,
            "coverage_threshold": FINAL_ANSWER_MIN_COVERAGE,
            "scores_used": {key: scores.get(key) for key in ["answer_relevancy", "faithfulness", "context_recall"] if key in scores},
            "evidence": self.snippet(answer, matched_terms[0]) if matched_terms else "",
        }

    def match_terms(self, text: str, reference_terms: list[str]) -> list[str]:
        normalized = str(text or "").lower()
        return [term for term in reference_terms if term.lower() in normalized]

    def snippet(self, text: str, term: str, radius: int = 70) -> str:
        value = str(text or "")
        if not value:
            return ""
        index = value.lower().find(str(term or "").lower())
        if index < 0:
            return value[: radius * 2].strip()
        start = max(index - radius, 0)
        end = min(index + len(term) + radius, len(value))
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(value) else ""
        return f"{prefix}{value[start:end].strip()}{suffix}"

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

    def top_chunk_ids(self, results: list[dict], limit: int = 5) -> list[int | None]:
        return [item.get("chunk_id") for item in results[:limit]]

    def to_score_rows(self, ragas_result: Any) -> list[dict]:
        if hasattr(ragas_result, "to_pandas"):
            return ragas_result.to_pandas().to_dict(orient="records")
        if isinstance(ragas_result, dict):
            return self.rows_from_metric_dict(ragas_result)
        raise CommandError(f"Unsupported RAGAS result type: {type(ragas_result)!r}")

    def rows_from_metric_dict(self, scores: dict) -> list[dict]:
        row_count = max((len(value) for value in scores.values() if isinstance(value, list)), default=1)
        rows = []
        for index in range(row_count):
            row = {}
            for key, value in scores.items():
                row[key] = value[index] if isinstance(value, list) and index < len(value) else value
            rows.append(row)
        return rows

    def metric_name(self, metric: Any) -> str:
        return getattr(metric, "name", None) or getattr(metric, "__name__", None) or str(metric)

    def safe_float(self, value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return None if math.isnan(number) else round(number, 4)

    def mean_scores(self, results: list[dict], metric_names: list[str]) -> dict[str, float | None]:
        means = {}
        for metric_name in metric_names:
            values = [result["scores"].get(metric_name) for result in results]
            values = [value for value in values if value is not None]
            means[metric_name] = round(sum(values) / len(values), 4) if values else None
        return means

    def aggregate_retrieval_metrics(self, results: list[dict]) -> dict:
        stages = ["vector", "bm25", "hybrid", "rerank", "compression"]
        metrics = {}
        for stage in stages:
            diagnostics = [result.get("diagnostics", {}).get("stages", {}).get(stage, {}) for result in results]
            target_cases = [item for item in diagnostics if item.get("target_chunk_ids")]
            metric_cases = target_cases or diagnostics
            if not metric_cases:
                metrics[stage] = {"hit_rate": None, "recall_at_k": None, "mrr": None, "case_count": 0, "target_case_count": 0}
                continue
            hit_values = [1 if item.get("hit") else 0 for item in metric_cases]
            recall_values = [
                item.get("target_recall") if item.get("target_recall") is not None else (1 if item.get("hit") else 0)
                for item in metric_cases
            ]
            rr_values = [item.get("reciprocal_rank") or (1 if item.get("hit") else 0) for item in metric_cases]
            metrics[stage] = {
                "hit_rate": round(sum(hit_values) / len(hit_values), 4),
                "recall_at_k": round(sum(recall_values) / len(recall_values), 4),
                "mrr": round(sum(rr_values) / len(rr_values), 4),
                "case_count": len(metric_cases),
                "target_case_count": len(target_cases),
            }
        return metrics

    def normalize_judge_score(self, value: Any, default: float = 0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if math.isnan(number):
            return default
        return round(min(max(number, 0), 1), 4)

    def parse_judge_json(self, raw: str) -> dict:
        value = str(raw or "").strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE).strip()
            value = re.sub(r"\s*```$", "", value).strip()
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", value)
            if not match:
                raise
            parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("Judge response must be a JSON object.")
        return parsed

    def judge_prompt(self, result: dict) -> str:
        rubric = result.get("rubric") or {}
        contexts = result.get("contexts") or []
        compact_contexts = []
        for index, context in enumerate(contexts[:8], start=1):
            compact_contexts.append(f"[context {index}] {str(context or '')[:1800]}")
        schema = {
            "correctness_score": "number between 0 and 1",
            "citation_score": "number between 0 and 1",
            "hallucination_risk": "number between 0 and 1; higher means more risky",
            "reason": "short Chinese explanation, <= 160 chars",
        }
        return (
            "你是 AIAssistant/RAGPilot 的专家评测 Judge。请只根据给定的标准答案和检索上下文评价模型回答，"
            "不要引入外部知识。评分必须严格输出 JSON，不要输出 Markdown。\n\n"
            "评分定义：\n"
            "- correctness_score: 回答是否覆盖标准答案的核心事实，0 表示完全错误，1 表示完全正确。\n"
            "- citation_score: 回答中的关键结论是否能被 contexts 支撑，0 表示无支撑，1 表示充分支撑。\n"
            "- hallucination_risk: 回答是否包含 contexts/reference 不支持的编造或过度推断，0 表示低风险，1 表示高风险。\n"
            "- reason: 用中文简要说明主要扣分点或通过依据。\n\n"
            f"JSON Schema: {json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Question:\n{result.get('question', '')}\n\n"
            f"Reference Answer:\n{result.get('reference', '')}\n\n"
            f"Rubric:\n{json.dumps(rubric, ensure_ascii=False)}\n\n"
            f"Contexts:\n{chr(10).join(compact_contexts) or '无'}\n\n"
            f"Model Answer:\n{result.get('answer', '')}\n\n"
            "只输出形如 {\"correctness_score\":0.8,\"citation_score\":0.7,\"hallucination_risk\":0.1,\"reason\":\"...\"} 的 JSON。"
        )

    def score_with_llm_judge(self, result: dict) -> dict:
        prompt = self.judge_prompt(result)
        try:
            messages = [
                {"role": "system", "content": "You are a strict JSON-only RAG evaluation judge."},
                {"role": "user", "content": prompt},
            ]
            client = get_openai_client()
            try:
                completion = client.chat.completions.create(
                    model=settings.CHAT_MODEL,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"},
                )
            except Exception as exc:
                if "response_format" not in str(exc).lower() and "json" not in str(exc).lower():
                    raise
                completion = client.chat.completions.create(
                    model=settings.CHAT_MODEL,
                    messages=messages,
                    temperature=0,
                )
            raw = completion.choices[0].message.content or "{}"
            parsed = self.parse_judge_json(raw)
            normalized = {
                "correctness_score": self.normalize_judge_score(parsed.get("correctness_score")),
                "citation_score": self.normalize_judge_score(parsed.get("citation_score")),
                "hallucination_risk": self.normalize_judge_score(parsed.get("hallucination_risk")),
                "reason": str(parsed.get("reason") or "").strip()[:500],
                "raw": parsed,
                "model": settings.CHAT_MODEL,
                "prompt_version": "rag_judge_v1",
            }
            thresholds = result.get("thresholds") or {}
            min_correctness = self.normalize_judge_score(thresholds.get("min_correctness_score", 0.7), 0.7)
            min_citation = self.normalize_judge_score(thresholds.get("min_citation_score", 0.6), 0.6)
            max_hallucination = self.normalize_judge_score(thresholds.get("max_hallucination_risk", 0.3), 0.3)
            normalized["thresholds"] = {
                "min_correctness_score": min_correctness,
                "min_citation_score": min_citation,
                "max_hallucination_risk": max_hallucination,
            }
            normalized["passed"] = (
                normalized["correctness_score"] >= min_correctness
                and normalized["citation_score"] >= min_citation
                and normalized["hallucination_risk"] <= max_hallucination
            )
            return normalized
        except Exception as exc:
            return {
                "passed": False,
                "error": str(exc),
                "correctness_score": None,
                "citation_score": None,
                "hallucination_risk": None,
                "reason": "Judge 评分失败。",
                "model": settings.CHAT_MODEL,
                "prompt_version": "rag_judge_v1",
            }

    def aggregate_judge_results(self, results: list[dict]) -> dict:
        judge_rows = [item.get("judge_results") or {} for item in results if item.get("judge_results")]
        scored = [item for item in judge_rows if item.get("correctness_score") is not None]
        if not scored:
            return {"case_count": 0, "pass_rate": None}
        passed_count = sum(1 for item in scored if item.get("passed"))
        def mean(key: str):
            values = [item.get(key) for item in scored if item.get(key) is not None]
            return round(sum(values) / len(values), 4) if values else None
        return {
            "case_count": len(scored),
            "passed_count": passed_count,
            "failed_count": len(scored) - passed_count,
            "pass_rate": round(passed_count / len(scored), 4),
            "mean_correctness_score": mean("correctness_score"),
            "mean_citation_score": mean("citation_score"),
            "mean_hallucination_risk": mean("hallucination_risk"),
        }

    def print_results(self, payload: dict):
        self.stdout.write("")
        for result in payload["results"]:
            self.stdout.write(f"[{result['id']}]")
            self.stdout.write(f"  question: {result['question']}")
            self.stdout.write(f"  rewrite: {result['rewrite_strategy']} -> {result['rewritten_query']}")
            self.stdout.write(f"  contexts: {result['context_count']}")
            for metric_name, score in result["scores"].items():
                self.stdout.write(f"  {metric_name}: {score}")
            deterministic = result.get("deterministic_results") or {}
            if deterministic.get("total_count"):
                self.stdout.write(
                    f"  deterministic: {deterministic.get('passed_count')}/{deterministic.get('total_count')} "
                    f"passed={deterministic.get('passed')}"
                )
            judge = result.get("judge_results") or {}
            if judge:
                self.stdout.write(
                    f"  judge: correctness={judge.get('correctness_score')} "
                    f"citation={judge.get('citation_score')} hallucination={judge.get('hallucination_risk')} "
                    f"passed={judge.get('passed')}"
                )
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("RAGAS mean scores"))
        for metric_name, score in payload["summary"]["mean_scores"].items():
            self.stdout.write(f"  {metric_name}: {score}")
        if payload["summary"].get("eval_run_id"):
            self.stdout.write(f"Saved eval run: #{payload['summary']['eval_run_id']}")

    def save_eval_results(self, eval_run: RagEvalRun, results: list[dict], summary: dict):
        RagEvalCaseResult.objects.bulk_create(
            [
                RagEvalCaseResult(
                    run=eval_run,
                    case_id=result["id"],
                    question=result["question"],
                    reference=result["reference"],
                    case_type=result.get("case_type", ""),
                    suite=result.get("suite", ""),
                    answer=result["answer"],
                    rewritten_query=result["rewritten_query"],
                    rewrite_strategy=result["rewrite_strategy"],
                    contexts=result["contexts"],
                    scores=result["scores"],
                    compression_stats=result["compression_stats"],
                    top_chunks=result["top_chunks"],
                    diagnostics=result.get("diagnostics", {}),
                    deterministic_results=result.get("deterministic_results", {}),
                    judge_results=result.get("judge_results", {}),
                    execution_metrics={
                        "latency_ms": result.get("latency_ms", 0),
                        "estimated_total_tokens": result.get("estimated_total_tokens", 0),
                    },
                )
                for result in results
            ]
        )
        eval_run.status = "completed"
        eval_run.mean_scores = summary["mean_scores"]
        eval_run.retrieval_metrics = {
            **summary.get("retrieval_metrics", {}),
            "deterministic": summary.get("deterministic", {}),
            "judge": summary.get("judge", {}),
        }
        eval_run.case_count = len(results)
        eval_run.execution_metrics = {
            "avg_latency_ms": round(sum(float(item.get("latency_ms") or 0) for item in results) / len(results), 2) if results else 0,
            "total_estimated_tokens": sum(int(item.get("estimated_total_tokens") or 0) for item in results),
        }
        eval_run.finished_at = timezone.now()
        eval_run.save(update_fields=["status", "mean_scores", "retrieval_metrics", "case_count", "execution_metrics", "finished_at"])
