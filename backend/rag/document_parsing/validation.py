from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

from charset_normalizer import from_bytes
from django.conf import settings


class DocumentValidationError(ValueError):
    pass


def _read_upload(uploaded) -> bytes:
    uploaded.seek(0)
    data = uploaded.read()
    uploaded.seek(0)
    return data


def _validate_docx(data: bytes) -> None:
    if not data.startswith(b"PK"):
        raise DocumentValidationError("DOCX 文件签名无效。")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise DocumentValidationError("文件不是有效的 DOCX 文档。")
            if len(archive.infolist()) > settings.DOCUMENT_MAX_DOCX_FILES:
                raise DocumentValidationError("DOCX 内部文件数量异常，已拒绝处理。")
            total = sum(item.file_size for item in archive.infolist())
            if total > settings.DOCUMENT_MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocumentValidationError("DOCX 解压后内容超过允许大小。")
            for item in archive.infolist():
                if item.compress_size and item.file_size / item.compress_size > settings.DOCUMENT_MAX_ZIP_RATIO:
                    raise DocumentValidationError("DOCX 压缩比异常，已拒绝处理。")
    except zipfile.BadZipFile as exc:
        raise DocumentValidationError("DOCX 文件已损坏。") from exc


def _validate_pdf(data: bytes) -> int:
    if not data.startswith(b"%PDF-"):
        raise DocumentValidationError("PDF 文件签名无效。")
    try:
        import fitz
        with fitz.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise DocumentValidationError("暂不支持加密 PDF，请先解除密码保护。")
            if pdf.page_count > settings.DOCUMENT_MAX_PDF_PAGES:
                raise DocumentValidationError(f"PDF 超过 {settings.DOCUMENT_MAX_PDF_PAGES} 页限制。")
            return pdf.page_count
    except DocumentValidationError:
        raise
    except Exception as exc:
        raise DocumentValidationError("PDF 文件已损坏或无法读取。") from exc


def _validate_text(data: bytes) -> str:
    if b"\x00" in data:
        raise DocumentValidationError("文本文件包含二进制内容。")
    match = from_bytes(data).best()
    if match is None:
        raise DocumentValidationError("无法识别文本文件编码。")
    return str(match.encoding or "utf-8")


def validate_document_file(uploaded) -> dict:
    filename = Path(uploaded.name or "").name
    extension = Path(filename).suffix.lower()
    allowed = {".txt", ".md", ".markdown", ".docx", ".pdf"}
    if extension not in allowed:
        raise DocumentValidationError("仅支持 TXT、Markdown、DOCX 和 PDF 文件。")
    size = int(getattr(uploaded, "size", 0) or 0)
    if size <= 0:
        raise DocumentValidationError("上传文件为空。")
    if size > settings.DOCUMENT_MAX_UPLOAD_BYTES:
        raise DocumentValidationError(f"文件超过 {settings.DOCUMENT_MAX_UPLOAD_BYTES // 1024 // 1024} MiB 限制。")
    data = _read_upload(uploaded)
    metadata = {"filename": filename, "size_bytes": size, "sha256": hashlib.sha256(data).hexdigest()}
    if extension == ".pdf":
        metadata.update(mime_type="application/pdf", page_count=_validate_pdf(data))
    elif extension == ".docx":
        _validate_docx(data)
        metadata.update(mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    else:
        encoding = _validate_text(data)
        metadata.update(
            mime_type="text/markdown" if extension in {".md", ".markdown"} else "text/plain",
            encoding=encoding,
        )
    return metadata
