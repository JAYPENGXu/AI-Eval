from unittest.mock import patch

import pytest
from django.test import override_settings

from rag.document_parsing.paddleocr import PaddleOcrClient, PaddleOcrError


@override_settings(PADDLEOCR_RESULT_HOST_ALLOWLIST=[".bcebos.com"])
def test_official_result_host_is_allowed_even_when_tun_dns_returns_reserved_ip():
    with patch("rag.document_parsing.paddleocr.socket.getaddrinfo") as resolve:
        PaddleOcrClient._validate_result_url("https://result.bcebos.com/job/result.jsonl")
    resolve.assert_not_called()


@override_settings(PADDLEOCR_RESULT_HOST_ALLOWLIST=[".bcebos.com"])
@pytest.mark.parametrize("url", [
    "http://result.bcebos.com/result.jsonl",
    "https://127.0.0.1/result.jsonl",
    "https://10.0.0.5/result.jsonl",
    "https://evilbcebos.com/result.jsonl",
])
def test_result_url_rejects_non_https_private_and_suffix_confusion(url):
    with patch(
        "rag.document_parsing.paddleocr.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("10.0.0.8", 443))],
    ):
        with pytest.raises(PaddleOcrError):
            PaddleOcrClient._validate_result_url(url)
