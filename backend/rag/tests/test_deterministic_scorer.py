from __future__ import annotations

from rag.management.commands.eval_ragas import Command


def scorer():
    return Command()


class TestDeterministicScorer:
    def test_scores_all_supported_checks_with_pass_details(self):
        result = {
            "router": {"query_intent": "internal_knowledge"},
            "rewritten_query": "需求评审 输入 输出",
            "answer": "需求评审需要 PRD 和技术方案，并引用来源 [1]。",
            "contexts": ["PRD、技术方案、评审记录都应保留在压缩上下文中。"],
            "diagnostics": {
                "stages": {
                    "vector": {"hit": True},
                    "bm25": {"hit": True},
                    "hybrid": {"hit": True},
                    "rerank": {"hit": True},
                }
            },
            "estimated_total_tokens": 900,
            "latency_ms": 1200,
            "deterministic_checks": {
                "router_intent": "internal_knowledge",
                "rewrite_contains": ["需求评审"],
                "answer_contains": ["PRD", "技术方案"],
                "answer_not_contains": ["无法回答"],
                "citation_required": True,
                "vector_hit": True,
                "bm25_hit": True,
                "hybrid_hit": True,
                "rerank_keep": True,
                "compression_keep_terms": ["评审记录"],
                "max_total_tokens": 1000,
                "max_latency_ms": 1500,
            },
            "thresholds": {"deterministic_min_pass_rate": 1},
        }

        scored = scorer().score_deterministic(result)

        assert scored["passed"] is True
        assert scored["passed_count"] == scored["total_count"] == 12
        assert scored["failed_count"] == 0
        assert {row["key"] for row in scored["checks"]} == {
            "router_intent",
            "rewrite_contains",
            "answer_contains",
            "answer_not_contains",
            "citation_required",
            "vector_hit",
            "bm25_hit",
            "hybrid_hit",
            "rerank_keep",
            "compression_keep_terms",
            "max_total_tokens",
            "max_latency_ms",
        }

    def test_reports_failed_checks_and_applies_min_pass_rate(self):
        result = {
            "router": {"query_intent": "web_required"},
            "rewritten_query": "天气",
            "answer": "无法回答，也没有引用。",
            "contexts": ["上下文缺少目标词"],
            "diagnostics": {"stages": {"vector": {"hit": False}}},
            "estimated_total_tokens": 1600,
            "latency_ms": 2500,
            "deterministic_checks": {
                "router_intent": "internal_knowledge",
                "answer_contains": ["PRD"],
                "answer_not_contains": ["无法回答"],
                "vector_hit": True,
                "max_total_tokens": 1000,
                "max_latency_ms": 2000,
            },
            "thresholds": {"deterministic_min_pass_rate": 0.8},
        }

        scored = scorer().score_deterministic(result)
        failed = {row["key"]: row for row in scored["checks"] if not row["passed"]}

        assert scored["passed"] is False
        assert scored["pass_rate"] == 0
        assert scored["failed_count"] == 6
        assert set(failed) == {
            "router_intent",
            "answer_contains",
            "answer_not_contains",
            "vector_hit",
            "max_total_tokens",
            "max_latency_ms",
        }
        assert failed["answer_contains"]["actual"]["missing"] == ["PRD"]
        assert failed["answer_not_contains"]["actual"]["found"] == ["无法回答"]

    def test_empty_checks_are_neutral(self):
        scored = scorer().score_deterministic({"deterministic_checks": {}, "thresholds": {}})

        assert scored["passed"] is True
        assert scored["pass_rate"] is None
        assert scored["total_count"] == 0
