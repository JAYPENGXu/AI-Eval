from unittest.mock import patch

import pytest

from rag.demo_reset import CORE_RAG_CASES, reset_demo_runtime
from rag.demo_seed import seed_demo_workspace
from rag.models import RagBenchmarkCase


@pytest.mark.django_db(transaction=True)
def test_runtime_reset_removes_visitor_cases_without_touching_fixed_suites(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.DEMO_MODE = True
    kb = seed_demo_workspace(process=False)["knowledge_base"]
    RagBenchmarkCase.objects.create(
        kb=kb,
        case_id="visitor-case",
        question="临时问题",
        reference="临时答案",
        suite="regression",
    )

    with patch("rag.vector_store.get_vector_store"):
        reset_demo_runtime()

    remaining = set(RagBenchmarkCase.objects.filter(kb=kb).values_list("case_id", flat=True))
    assert "visitor-case" not in remaining
    assert remaining == CORE_RAG_CASES
