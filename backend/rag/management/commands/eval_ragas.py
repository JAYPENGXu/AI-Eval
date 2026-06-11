from __future__ import annotations

import json
import math
import re
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
                results.append({**pipeline_result, "scores": scores})

            summary = {
                "kb": {"id": kb.id, "name": kb.name},
                "case_count": len(results),
                "metrics": metric_names,
                "mean_scores": self.mean_scores(results, metric_names),
                "retrieval_metrics": self.aggregate_retrieval_metrics(results),
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
                    "tags": item.tags,
                    "expected_terms": item.expected_terms,
                    "target_chunk_ids": item.target_chunk_ids,
                    "suite": item.suite,
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

        rewrite_result = rewrite_query(question, options["query_rewrite_strategy"])
        retrieval_query = rewrite_result["rewritten_query"]
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
            "rewritten_query": retrieval_query,
            "rewrite_strategy": rewrite_result["rewrite_strategy"],
            "answer": answer,
            "contexts": contexts,
            "context_count": len(contexts),
            "expected_terms": expected_terms,
            "target_chunk_ids": target_chunk_ids,
            "diagnostics": diagnostics,
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

    def print_results(self, payload: dict):
        self.stdout.write("")
        for result in payload["results"]:
            self.stdout.write(f"[{result['id']}]")
            self.stdout.write(f"  question: {result['question']}")
            self.stdout.write(f"  rewrite: {result['rewrite_strategy']} -> {result['rewritten_query']}")
            self.stdout.write(f"  contexts: {result['context_count']}")
            for metric_name, score in result["scores"].items():
                self.stdout.write(f"  {metric_name}: {score}")
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
                    answer=result["answer"],
                    rewritten_query=result["rewritten_query"],
                    rewrite_strategy=result["rewrite_strategy"],
                    contexts=result["contexts"],
                    scores=result["scores"],
                    compression_stats=result["compression_stats"],
                    top_chunks=result["top_chunks"],
                    diagnostics=result.get("diagnostics", {}),
                )
                for result in results
            ]
        )
        eval_run.status = "completed"
        eval_run.mean_scores = summary["mean_scores"]
        eval_run.retrieval_metrics = summary.get("retrieval_metrics", {})
        eval_run.case_count = len(results)
        eval_run.finished_at = timezone.now()
        eval_run.save(update_fields=["status", "mean_scores", "retrieval_metrics", "case_count", "finished_at"])
