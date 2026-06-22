from __future__ import annotations

import time
from django.conf import settings
from django.utils import timezone

from .access_control import build_access_scope
from .bm25 import bm25_search
from .compression import compress_context
from .hybrid import rrf_fusion
from .models import Chunk, RagBenchmarkCase, RagEvalCaseResult, RagEvalRun
from .query_rewrite import rewrite_query
from .rerank import rerank_candidates
from .retrieval import retrieve

STAGE_NAMES = ("vector", "bm25", "hybrid", "rerank", "compression")


def _ids(items):
    return {int(item["chunk_id"]) for item in items or [] if item.get("chunk_id") is not None}


def execute_security_eval_run(eval_run: RagEvalRun, options: dict | None = None) -> RagEvalRun:
    options = options or {}
    cases = list(RagBenchmarkCase.objects.filter(kb=eval_run.kb, suite="security", enabled=True).select_related("principal_membership__user"))
    results = []
    latencies = []
    for case in cases:
        started = time.monotonic()
        principal = case.principal_membership
        stages = {name: [] for name in STAGE_NAMES}
        forbidden_chunks = {int(value) for value in case.forbidden_chunk_ids or []}
        forbidden_documents = {int(value) for value in case.forbidden_document_ids or []}
        expected_documents = {int(value) for value in case.expected_authorized_document_ids or []}
        error = ""
        if not principal:
            error = "Security case has no principal membership."
        else:
            scope = build_access_scope(principal.user, kb=eval_run.kb)
            if scope.can_knowledge_base(eval_run.kb, "query"):
                try:
                    rewritten = rewrite_query(case.question, "rule")["rewritten_query"]
                    vector = retrieve(eval_run.kb, rewritten, top_k=options.get("top_k") or settings.RAG_TOP_K, scope=scope, context={"owner": principal.user})
                    bm25 = bm25_search(eval_run.kb, rewritten, top_k=options.get("bm25_top_k") or settings.BM25_TOP_K, scope=scope)
                    hybrid = rrf_fusion(bm25, vector, top_k=max(options.get("top_k") or settings.RAG_TOP_K, options.get("bm25_top_k") or settings.BM25_TOP_K), rrf_k=options.get("rrf_k") or settings.RRF_K)
                    stages.update({"vector": vector, "bm25": bm25, "hybrid": hybrid})
                    pre_model_ids = _ids([*vector, *bm25, *hybrid])
                    pre_model_docs = dict(Chunk.objects.filter(id__in=pre_model_ids).values_list("id", "document_id"))
                    unsafe = any(chunk_id in forbidden_chunks or pre_model_docs.get(chunk_id) in forbidden_documents or (expected_documents and pre_model_docs.get(chunk_id) not in expected_documents) for chunk_id in pre_model_ids)
                    if not unsafe:
                        rerank = rerank_candidates(rewritten, hybrid, top_n=options.get("rerank_top_n") or settings.RERANK_TOP_N, context={"owner": principal.user, "kb": eval_run.kb})
                        compression_strategy = options.get("compression_strategy") or settings.CONTEXT_COMPRESSION_STRATEGY
                        if compression_strategy == "llm": compression_strategy = "structure_aware"
                        compressed, _ = compress_context(rewritten, rerank, strategy=compression_strategy, context={"owner": principal.user, "kb": eval_run.kb})
                        stages.update({"rerank": rerank, "compression": compressed})
                except Exception as exc:
                    error = str(exc)
        stage_details = {}
        all_unauthorized = set()
        for name, items in stages.items():
            ids = _ids(items)
            doc_map = dict(Chunk.objects.filter(id__in=ids).values_list("id", "document_id"))
            unauthorized = {chunk_id for chunk_id in ids if chunk_id in forbidden_chunks or doc_map.get(chunk_id) in forbidden_documents}
            unauthorized.update({chunk_id for chunk_id in ids if expected_documents and doc_map.get(chunk_id) not in expected_documents})
            all_unauthorized.update(unauthorized)
            stage_details[name] = {"passed": not unauthorized, "returned_chunk_ids": sorted(ids), "unauthorized_chunk_ids": sorted(unauthorized), "expected_document_ids": sorted(expected_documents)}
        passed = not all_unauthorized and not error
        latency = round((time.monotonic() - started) * 1000)
        latencies.append(latency)
        results.append(RagEvalCaseResult(
            run=eval_run, case_id=case.case_id, question=case.question, reference=case.reference,
            case_type="security_acl", suite="security", answer="", contexts=[], scores={"security_pass": 1.0 if passed else 0.0},
            diagnostics={"retrieval_only": True, "principal_membership": principal.id if principal else None, "stages": stage_details},
            deterministic_results={"passed": passed, "total_count": 1, "passed_count": 1 if passed else 0, "failed_count": 0 if passed else 1,
                "checks": [{"type": "unauthorized_recall_zero", "passed": passed, "actual": sorted(all_unauthorized), "expected": []}]},
            judge_results={}, execution_metrics={"latency_ms": latency, "llm_answer_calls": 0}, error_message=error,
        ))
    eval_run.case_results.all().delete()
    RagEvalCaseResult.objects.bulk_create(results)
    passed_count = sum(1 for item in results if item.deterministic_results.get("passed"))
    eval_run.status = "completed"
    eval_run.case_count = len(results)
    eval_run.mean_scores = {"security_pass_rate": round(passed_count / len(results), 4) if results else 0}
    eval_run.retrieval_metrics = {"unauthorized_recall_zero": passed_count == len(results), "passed_count": passed_count, "failed_count": len(results) - passed_count}
    eval_run.execution_metrics = {"p50_latency_ms": sorted(latencies)[len(latencies)//2] if latencies else 0, "max_latency_ms": max(latencies) if latencies else 0, "llm_answer_calls": 0}
    eval_run.finished_at = timezone.now()
    eval_run.save(update_fields=["status", "case_count", "mean_scores", "retrieval_metrics", "execution_metrics", "finished_at"])
    return eval_run
