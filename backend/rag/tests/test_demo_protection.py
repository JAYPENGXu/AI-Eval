import pytest
from rest_framework.test import APIClient

from rag.demo_seed import seed_demo_workspace
from rag.models import Document, KnowledgeBase, Organization


@pytest.mark.django_db(transaction=True)
def test_seed_documents_reject_structural_writes_in_public_demo(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.DEMO_MODE = True
    seed_demo_workspace(process=False)
    client = APIClient()
    login = client.post("/api/demo/persona-login/", {"username": "demo_owner"}, format="json")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    organization = Organization.objects.get(slug="demo-xinghai")
    kb = KnowledgeBase.objects.get(organization=organization, name="星海科技企业知识库")
    document = Document.objects.get(kb=kb, filename="ragpilot_demo_guide.pdf")
    alternate_policy = organization.access_policies.get(name="研发机密资料")

    assert client.patch(
        f"/api/documents/{document.id}/",
        {"access_policy": alternate_policy.id},
        format="json",
    ).status_code == 403
    assert client.post(f"/api/documents/{document.id}/parse/", {}, format="json").status_code == 403
    assert client.post(f"/api/documents/{document.id}/index/", {}, format="json").status_code == 403
    assert client.post(
        f"/api/documents/{document.id}/set-access-policy/",
        {"access_policy": alternate_policy.id},
        format="json",
    ).status_code == 403
    assert client.post(f"/api/knowledge-bases/{kb.id}/reindex-stale/", {}, format="json").status_code == 403
