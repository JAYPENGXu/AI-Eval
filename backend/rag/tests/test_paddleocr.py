from __future__ import annotations

import json
from unittest.mock import patch

import responses
from django.test import override_settings

from rag.document_parsing.paddleocr import PaddleOcrClient


@responses.activate
@override_settings(
    PADDLEOCR_JOB_URL="https://paddleocr.example/api/v2/ocr/jobs",
    PADDLEOCR_TOKEN="top-secret-token",
    PADDLEOCR_MODEL="PaddleOCR-VL-1.6",
    PADDLEOCR_POLL_INTERVAL_SECONDS=0,
    PADDLEOCR_HTTP_RETRIES=0,
)
def test_paddle_job_submit_poll_and_jsonl_download(tmp_path):
    job_url = "https://paddleocr.example/api/v2/ocr/jobs"
    result_url = "https://objects.example/result.jsonl"
    responses.add(responses.POST, job_url, json={"data": {"jobId": "job-1"}}, status=200)
    responses.add(
        responses.GET,
        f"{job_url}/job-1",
        json={
            "data": {
                "state": "done",
                "extractProgress": {"totalPages": 1, "extractedPages": 1},
                "resultUrl": {"jsonUrl": result_url},
            }
        },
        status=200,
    )
    body = json.dumps({
        "result": {
            "layoutParsingResults": [
                {"markdown": {"text": "# 标题\n\nOCR 正文", "images": {}}, "outputImages": {}}
            ]
        }
    })
    responses.add(responses.GET, result_url, body=body, status=200)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.7 test")

    jobs = []
    with patch.object(PaddleOcrClient, "_validate_result_url", return_value=None):
        pages = PaddleOcrClient().parse(path, job_callback=jobs.append)

    assert jobs == ["job-1"]
    assert pages == ["# 标题\n\nOCR 正文"]
    authorization = responses.calls[0].request.headers["Authorization"]
    assert authorization == "bearer top-secret-token"
