from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from rag.case_factory import (
    create_regression_case_from_eval_case,
    create_regression_case_from_trace,
    create_regression_case_from_user_feedback,
)
from rag.models import ChatMessage, ChatSession, KnowledgeBase, RagEvalCaseResult, RagEvalRun, RagTrace, RagUserFeedback


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(username="case-owner", password="pass")


@pytest.fixture
def kb(owner):
    return KnowledgeBase.objects.create(owner=owner, name="KB")


@pytest.fixture
def trace(owner, kb):
    session = ChatSession.objects.create(owner=owner, kb=kb, title="Debug")
    answer = ChatMessage.objects.create(session=session, role="assistant", content="原始回答，仍需专家复核。")
    return RagTrace.objects.create(
        session=session,
        message=answer,
        question="需求评审阶段需要哪些输入？",
        rewritten_query="需求评审 输入",
        vector_results=[],
        bm25_results=[],
        hybrid_results=[],
        rerank_results=[],
    )


@pytest.mark.django_db
class TestRegressionCaseFactoryIdempotency:
    def test_trace_conversion_is_idempotent_without_overwriting_expert_edits(self, owner, trace):
        first = create_regression_case_from_trace(user=owner, trace_id=trace.id)
        assert first.created is True
        assert first.case.case_id == f"trace_{trace.id}"

        first.case.reference = "专家修订后的标准答案"
        first.case.expected_terms = ["需求", "评审"]
        first.case.enabled = True
        first.case.save(update_fields=["reference", "expected_terms", "enabled", "updated_at"])

        second = create_regression_case_from_trace(user=owner, trace_id=trace.id)
        second.case.refresh_from_db()

        assert second.created is False
        assert second.case.id == first.case.id
        assert second.case.reference == "专家修订后的标准答案"
        assert second.case.expected_terms == ["需求", "评审"]
        assert second.case.enabled is True

    def test_eval_failure_conversion_is_idempotent_without_overwriting_expert_edits(self, owner, kb):
        run = RagEvalRun.objects.create(kb=kb, status="completed", settings={})
        result = RagEvalCaseResult.objects.create(
            run=run,
            case_id="case-001",
            question="发布前需要做什么？",
            reference="原始参考答案",
            diagnostics={"stages": {"vector": {"hit": False, "target_chunk_ids": [101]}}},
        )

        first = create_regression_case_from_eval_case(user=owner, eval_case_result_id=result.id)
        first.case.reference = "专家修订后的发布标准答案"
        first.case.target_chunk_ids = [202, 303]
        first.case.save(update_fields=["reference", "target_chunk_ids", "updated_at"])

        second = create_regression_case_from_eval_case(user=owner, eval_case_result_id=result.id)
        second.case.refresh_from_db()

        assert second.created is False
        assert second.case.id == first.case.id
        assert second.case.reference == "专家修订后的发布标准答案"
        assert second.case.target_chunk_ids == [202, 303]

    def test_feedback_conversion_is_idempotent_without_overwriting_expert_edits(self, owner, trace):
        feedback = RagUserFeedback.objects.create(
            owner=owner,
            kb=trace.session.kb,
            session=trace.session,
            message=trace.message,
            trace=trace,
            rating="not_helpful",
            reason="insufficient_context",
            failure_signals=[{"code": "user_negative_feedback"}],
        )

        first = create_regression_case_from_user_feedback(user=owner, feedback_id=feedback.id)
        first.case.reference = "专家修订后的反馈标准答案"
        first.case.rubric = {"dimensions": [{"name": "correctness"}]}
        first.case.save(update_fields=["reference", "rubric", "updated_at"])

        second = create_regression_case_from_user_feedback(user=owner, feedback_id=feedback.id)
        second.case.refresh_from_db()

        assert second.created is False
        assert second.case.id == first.case.id
        assert second.case.reference == "专家修订后的反馈标准答案"
        assert second.case.rubric == {"dimensions": [{"name": "correctness"}]}
