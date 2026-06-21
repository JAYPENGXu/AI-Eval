from __future__ import annotations

import ipaddress
import json
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings


class PaddleOcrError(RuntimeError):
    pass


class PaddleOcrClient:
    def __init__(self) -> None:
        self.job_url = settings.PADDLEOCR_JOB_URL.rstrip("/")
        self.token = settings.PADDLEOCR_TOKEN
        self.model = settings.PADDLEOCR_MODEL
        if not self.job_url or not self.token:
            raise PaddleOcrError("检测到扫描页，但 PaddleOCR Job URL 或 Token 未配置。")
        self.headers = {"Authorization": f"bearer {self.token}"}

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        last_error = None
        for attempt in range(settings.PADDLEOCR_HTTP_RETRIES + 1):
            try:
                response = requests.request(
                    method, url, timeout=(settings.PADDLEOCR_CONNECT_TIMEOUT, settings.PADDLEOCR_READ_TIMEOUT), **kwargs
                )
                if response.status_code not in {429, 500, 502, 503, 504}:
                    return response
                last_error = PaddleOcrError(f"PaddleOCR 服务返回 HTTP {response.status_code}。")
            except requests.RequestException as exc:
                last_error = exc
            if attempt < settings.PADDLEOCR_HTTP_RETRIES:
                time.sleep(min(2 ** attempt, 8))
        raise PaddleOcrError(f"PaddleOCR 请求失败：{last_error}") from last_error

    def submit(self, pdf_path: Path) -> str:
        data = {
            "model": self.model,
            "optionalPayload": json.dumps({
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useChartRecognition": False,
            }),
        }
        response = None
        last_error = None
        for attempt in range(settings.PADDLEOCR_HTTP_RETRIES + 1):
            try:
                with pdf_path.open("rb") as stream:
                    response = requests.post(
                        self.job_url,
                        headers=self.headers,
                        data=data,
                        files={"file": (pdf_path.name, stream, "application/pdf")},
                        timeout=(settings.PADDLEOCR_CONNECT_TIMEOUT, settings.PADDLEOCR_READ_TIMEOUT),
                    )
                if response.status_code not in {429, 500, 502, 503, 504}:
                    break
                last_error = PaddleOcrError(f"PaddleOCR 服务返回 HTTP {response.status_code}。")
            except requests.RequestException as exc:
                last_error = exc
            if attempt < settings.PADDLEOCR_HTTP_RETRIES:
                time.sleep(min(2 ** attempt, 8))
        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else "network_error"
            raise PaddleOcrError(f"PaddleOCR 提交失败：{status}，{last_error or '请求未成功'}")
        try:
            return str(response.json()["data"]["jobId"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PaddleOcrError("PaddleOCR 提交响应缺少 jobId。") from exc

    def wait(self, job_id: str, progress_callback=None) -> str:
        deadline = time.monotonic() + settings.PADDLEOCR_JOB_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            response = self._request("GET", f"{self.job_url}/{job_id}", headers=self.headers)
            if response.status_code != 200:
                raise PaddleOcrError(f"PaddleOCR 状态查询失败，HTTP {response.status_code}。")
            try:
                data = response.json()["data"]
                state = data["state"]
            except (KeyError, TypeError, ValueError) as exc:
                raise PaddleOcrError("PaddleOCR 状态响应格式无效。") from exc
            progress = data.get("extractProgress") or {}
            if progress_callback:
                progress_callback(int(progress.get("extractedPages") or 0), int(progress.get("totalPages") or 0))
            if state == "done":
                try:
                    return str(data["resultUrl"]["jsonUrl"])
                except (KeyError, TypeError) as exc:
                    raise PaddleOcrError("PaddleOCR 完成响应缺少 JSONL URL。") from exc
            if state == "failed":
                raise PaddleOcrError(f"PaddleOCR 任务失败：{data.get('errorMsg') or '未知错误'}")
            if state not in {"pending", "running"}:
                raise PaddleOcrError(f"PaddleOCR 返回未知任务状态：{state}")
            time.sleep(settings.PADDLEOCR_POLL_INTERVAL_SECONDS)
        raise PaddleOcrError("PaddleOCR 任务等待超时。")

    @staticmethod
    def _validate_result_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise PaddleOcrError("PaddleOCR 结果 URL 必须是有效 HTTPS 地址。")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise PaddleOcrError("无法解析 PaddleOCR 结果地址。") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise PaddleOcrError("PaddleOCR 结果地址指向非公网网络，已拒绝下载。")

    def download_markdown_pages(self, result_url: str) -> list[str]:
        self._validate_result_url(result_url)
        response = self._request("GET", result_url, stream=True, allow_redirects=False)
        if response.status_code != 200:
            raise PaddleOcrError(f"PaddleOCR 结果下载失败，HTTP {response.status_code}。")
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            size += len(chunk)
            if size > settings.PADDLEOCR_MAX_RESULT_BYTES:
                raise PaddleOcrError("PaddleOCR 结果超过允许大小。")
            chunks.append(chunk)
        try:
            text = b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PaddleOcrError("PaddleOCR JSONL 不是有效 UTF-8。") from exc
        pages = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                result = json.loads(line)["result"]
                entries = result["layoutParsingResults"]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise PaddleOcrError("PaddleOCR JSONL 结果格式无效。") from exc
            for entry in entries:
                pages.append(str(((entry.get("markdown") or {}).get("text")) or ""))
        return pages

    def parse(self, pdf_path: Path, progress_callback=None, job_callback=None) -> list[str]:
        job_id = self.submit(pdf_path)
        if job_callback:
            job_callback(job_id)
        result_url = self.wait(job_id, progress_callback=progress_callback)
        return self.download_markdown_pages(result_url)
