from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from rag.models import Document, DocumentPage, DocumentParseRun, KnowledgeBase


@pytest.fixture
def api_user():
    user = User.objects.create_user(username="document-api-user", password="secret")
    client = APIClient()
    client.force_authenticate(user)
    return user, client


@pytest.mark.django_db(transaction=True)
def test_upload_validates_and_queues_parse_run(tmp_path, settings, api_user):
    settings.MEDIA_ROOT = tmp_path / "media"
    user, client = api_user
    kb = KnowledgeBase.objects.create(owner=user, name="KB")
    uploaded = SimpleUploadedFile(
        "guide.md",
        "# 标题\n\n这是用于解析层 API 测试的正文内容。".encode(),
        content_type="text/markdown",
    )

    with patch("rag.tasks.parse_document_task.delay", return_value=SimpleNamespace(id="task-1")) as delay:
        response = client.post("/api/documents/", {"kb": kb.id, "file": uploaded}, format="multipart")

    assert response.status_code == 201
    document = Document.objects.get(id=response.data["id"])
    run = document.parse_runs.get()
    assert document.mime_type == "text/markdown"
    assert document.sha256
    assert run.status == "queued"
    assert run.celery_task_id == "task-1"
    delay.assert_called_once_with(run.id)


@pytest.mark.django_db
def test_upload_rejects_extension_signature_mismatch(tmp_path, settings, api_user):
    settings.MEDIA_ROOT = tmp_path / "media"
    user, client = api_user
    kb = KnowledgeBase.objects.create(owner=user, name="KB")
    uploaded = SimpleUploadedFile("fake.pdf", b"plain text", content_type="application/pdf")

    response = client.post("/api/documents/", {"kb": kb.id, "file": uploaded}, format="multipart")

    assert response.status_code == 400
    assert Document.objects.count() == 0


@pytest.mark.django_db
def test_accept_parse_unlocks_preview_and_chunking(tmp_path, settings, api_user):
    settings.MEDIA_ROOT = tmp_path / "media"
    user, client = api_user
    kb = KnowledgeBase.objects.create(owner=user, name="KB")
    document = Document.objects.create(
        kb=kb,
        filename="guide.md",
        file=SimpleUploadedFile("guide.md", b"# guide"),
        file_type="md",
        mime_type="text/markdown",
        status="needs_review",
    )
    run = DocumentParseRun.objects.create(
        document=document,
        status="needs_review",
        parser="text",
        parser_version="1",
        quality_metrics={"text_coverage_rate": 0.8},
    )
    DocumentPage.objects.create(
        parse_run=run,
        page_number=1,
        text="需要人工确认的解析正文。",
        blocks=[{
            "id": "p1-b1", "type": "paragraph", "text": "需要人工确认的解析正文。",
            "page": 1, "heading_path": [], "bbox": [], "confidence": None,
            "metadata": {"paragraph": 1},
        }],
        char_count=12,
    )

    preview = client.get(f"/api/documents/{document.id}/parse-preview/?page=1")
    accepted = client.post(
        f"/api/documents/{document.id}/accept-parse/",
        {"parse_run_id": run.id},
        format="json",
    )
    chunks = client.post(
        f"/api/documents/{document.id}/chunk-preview/",
        {"chunk_method": "sentence", "options": {}, "parse_run_id": run.id},
        format="json",
    )

    assert preview.status_code == 200
    assert preview.data["page"]["page_number"] == 1
    assert accepted.status_code == 200
    assert accepted.data["status"] == "completed"
    assert chunks.status_code == 200
    assert chunks.data["chunks"][0]["metadata"]["parse_run_id"] == run.id
