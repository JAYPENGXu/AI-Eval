from __future__ import annotations

import pytest

from rag.query_router import blocked_route_answer, classify_query_route


class TestClassifyQueryRoute:
    def test_empty_query_is_rejected(self):
        decision = classify_query_route("", None)

        assert decision.query_intent == "unsupported"
        assert decision.route_decision == "reject"
        assert decision.confidence == 1.0

    def test_whitespace_only_query_is_rejected(self):
        decision = classify_query_route("   ", "  ")

        assert decision.route_decision == "reject"

    @pytest.mark.parametrize(
        "question",
        [
            "今天上海天气怎么样？",
            "最新的 AI 新闻有哪些？",
            "现在比特币价格是多少？",
            "please search the web for latest release notes",
            "What is the current stock price of Tesla?",
        ],
    )
    def test_web_required_queries_are_rejected_without_web_tool(self, question: str):
        decision = classify_query_route(question)

        assert decision.query_intent == "web_required"
        assert decision.route_decision == "reject_without_web_tool"
        assert decision.confidence >= 0.8

    @pytest.mark.parametrize(
        "question",
        [
            "你好",
            "Hello",
            "在吗",
            "讲个笑话",
            "你是谁",
        ],
    )
    def test_chitchat_queries_are_rejected(self, question: str):
        decision = classify_query_route(question)

        assert decision.query_intent == "unsupported"
        assert decision.route_decision == "reject"

    @pytest.mark.parametrize(
        "question",
        [
            "需求分析阶段需要哪些输入？",
            "发布流程中的评审节点是什么？",
            "Milvus 索引如何重建？",
        ],
    )
    def test_internal_knowledge_questions_enter_rag(self, question: str):
        decision = classify_query_route(question)

        assert decision.query_intent == "internal_knowledge"
        assert decision.route_decision == "rag"
        assert decision.confidence > 0

    def test_standalone_query_is_considered_with_original(self):
        decision = classify_query_route("它呢？", "需求分析阶段的交付物有哪些？")

        assert decision.query_intent == "internal_knowledge"
        assert decision.route_decision == "rag"

    def test_web_signal_in_rewritten_query_triggers_web_required(self):
        decision = classify_query_route("这个怎么样？", "最新的发布流程是什么？")

        assert decision.query_intent == "web_required"
        assert decision.route_decision == "reject_without_web_tool"

    def test_as_dict_matches_public_fields(self):
        decision = classify_query_route("需求评审由谁负责？")

        payload = decision.as_dict()

        assert payload == {
            "query_intent": decision.query_intent,
            "route_decision": decision.route_decision,
            "route_reason": decision.route_reason,
            "confidence": decision.confidence,
        }


class TestBlockedRouteAnswer:
    def test_web_required_message_mentions_missing_web_search(self):
        decision = classify_query_route("今天天气怎么样？")

        answer = blocked_route_answer(decision)

        assert "Web Search" in answer or "联网" in answer

    def test_unsupported_message_mentions_knowledge_base_scope(self):
        decision = classify_query_route("你好")

        answer = blocked_route_answer(decision)

        assert "知识库" in answer
