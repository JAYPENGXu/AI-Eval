from unittest.mock import patch

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from rag.demo_reset import reset_demo_runtime
from rag.demo_seed import DEMO_SEED_VERSION, seed_demo_workspace
from rag.models import Document, KnowledgeBase, Organization, RagAgentAction, RagBenchmarkCase, RagEvalRun


@pytest.mark.django_db(transaction=True)
def test_demo_seed_is_idempotent_and_builds_complete_story(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    first = seed_demo_workspace(process=False)
    second = seed_demo_workspace(process=False)

    assert first["organization"].id == second["organization"].id
    assert Organization.objects.filter(is_demo=True, demo_seed_version=DEMO_SEED_VERSION).count() == 2
    assert Document.objects.filter(kb__organization__is_demo=True).count() == 7
    assert set(RagBenchmarkCase.objects.values_list("suite", flat=True)) == {
        "smoke", "benchmark", "regression", "release", "security",
    }
    assert RagEvalRun.objects.filter(settings__demo_seed=DEMO_SEED_VERSION).count() == 3
    assert RagAgentAction.objects.filter(source="demo_seed", status="pending").count() == 1


@pytest.mark.django_db(transaction=True)
def test_demo_persona_login_and_destructive_protection(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.DEMO_MODE = True
    seed_demo_workspace(process=False)
    client = APIClient()

    personas = client.get("/api/demo/personas/")
    login = client.post("/api/demo/persona-login/", {"username": "demo_owner"}, format="json")
    suspended = client.post("/api/demo/persona-login/", {"username": "demo_suspended"}, format="json")

    assert personas.status_code == 200
    assert len(personas.data["personas"]) == 6
    assert login.status_code == 200 and login.data["access"]
    assert suspended.status_code == 403

    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    organization = Organization.objects.get(slug="demo-xinghai")
    kb = KnowledgeBase.objects.get(organization=organization, name="星海科技企业知识库")
    assert client.delete(f"/api/knowledge-bases/{kb.id}/").status_code == 403
    assert client.post("/api/reset-workspace/", {"organization": organization.id}, format="json").status_code == 403


@pytest.mark.django_db(transaction=True)
def test_runtime_reset_preserves_indexable_fixtures_and_removes_visitor_state(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.DEMO_MODE = True
    result = seed_demo_workspace(process=False)
    organization = result["organization"]
    KnowledgeBase.objects.create(
        owner=organization.created_by,
        organization=organization,
        access_policy=organization.access_policies.first(),
        name="访客临时知识库",
    )

    with patch("rag.vector_store.get_vector_store"):
        report = reset_demo_runtime()

    assert report == {"organizations": 2}
    assert not KnowledgeBase.objects.filter(name="访客临时知识库").exists()
    assert KnowledgeBase.objects.filter(name="星海科技企业知识库").exists()
    assert Document.objects.filter(filename="xinghai_mixed_ocr_dr.pdf").exists()
    assert RagAgentAction.objects.get(source="demo_seed").status == "pending"


@pytest.mark.django_db(transaction=True)
def test_full_reset_command_requires_confirmation(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    seed_demo_workspace(process=False)
    with patch("rag.vector_store.get_vector_store"):
        call_command("reset_demo_workspace", confirm="demo-workspace", no_process=True)
    assert Organization.objects.filter(is_demo=True).count() == 2
