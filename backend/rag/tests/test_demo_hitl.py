import pytest
from rest_framework.test import APIClient

from rag.demo_seed import seed_demo_workspace
from rag.models import KnowledgeBase, RagAgentAction, RagConfigDeployment


@pytest.mark.django_db(transaction=True)
def test_demo_publish_and_rollback_require_separate_hitl_confirmations(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.DEMO_MODE = True
    seed_demo_workspace(process=False)
    client = APIClient()
    login = client.post("/api/demo/persona-login/", {"username": "demo_owner"}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    kb = KnowledgeBase.objects.get(name="星海科技企业知识库")
    publish = RagAgentAction.objects.get(source="demo_seed")
    published = client.post(f"/api/rag-agent-actions/{publish.id}/confirm/", {}, format="json")

    assert published.status_code == 200
    assert published.data["status"] == "completed"
    kb.refresh_from_db()
    assert kb.active_config_version.version == 2
    assert RagConfigDeployment.objects.filter(kb=kb, operation="publish").count() == 1

    initial = kb.config_versions.get(version=1)
    rollback_request = client.post(
        f"/api/rag-config-versions/{initial.id}/request-rollback/",
        {"reason": "Demo 验证回滚"},
        format="json",
    )
    assert rollback_request.status_code == 201
    assert rollback_request.data["status"] == "pending"

    rolled_back = client.post(
        f"/api/rag-agent-actions/{rollback_request.data['id']}/confirm/",
        {},
        format="json",
    )
    assert rolled_back.status_code == 200
    assert rolled_back.data["status"] == "completed"
    kb.refresh_from_db()
    assert kb.active_config_version.version == 1
    assert RagConfigDeployment.objects.filter(kb=kb, operation="rollback").count() == 1
