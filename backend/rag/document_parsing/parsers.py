from __future__ import annotations

import re
import statistics
from abc import ABC, abstractmethod
from pathlib import Path

from charset_normalizer import from_bytes

from .ir import BlockIR, DocumentIR, PageIR

PARSER_VERSION = "1.0"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
LIST_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)]\s+)")


def non_whitespace_count(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def garbled_character_rate(text: str) -> float:
    chars = [char for char in text if not char.isspace()]
    if not chars:
        return 0.0
    suspicious = sum(
        1 for char in chars
        if char == "\ufffd" or (ord(char) < 32 and char not in "\n\r\t") or 0xE000 <= ord(char) <= 0xF8FF
    )
    return suspicious / len(chars)


def markdown_page(text: str, page_number: int, *, extraction_method: str = "native") -> PageIR:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[BlockIR] = []
    heading_stack: list[str] = []
    buffer: list[str] = []
    block_type = "paragraph"
    in_code = False

    def flush() -> None:
        nonlocal buffer, block_type
        value = "\n".join(buffer).strip()
        if value:
            blocks.append(BlockIR(
                id=f"p{page_number}-b{len(blocks) + 1}", type=block_type, text=value,
                page=page_number, heading_path=list(heading_stack), metadata={"paragraph": len(blocks) + 1},
            ))
        buffer = []
        block_type = "paragraph"

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                buffer.append(line)
                flush()
                in_code = False
            else:
                flush()
                in_code = True
                block_type = "code"
                buffer.append(line)
            continue
        if in_code:
            buffer.append(line)
            continue
        heading = HEADING_RE.match(stripped)
        if heading:
            flush()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(title)
            blocks.append(BlockIR(
                id=f"p{page_number}-b{len(blocks) + 1}", type="heading", text=title,
                page=page_number, heading_path=list(heading_stack), metadata={"level": level, "paragraph": len(blocks) + 1},
            ))
        elif not stripped:
            flush()
        else:
            current_type = "list" if LIST_RE.match(line) else ("table" if "|" in stripped and stripped.count("|") >= 2 else "paragraph")
            if buffer and current_type != block_type:
                flush()
            block_type = current_type
            buffer.append(line)
    flush()
    return PageIR(page_number=page_number, blocks=blocks, extraction_method=extraction_method, markdown=text)


class DocumentParser(ABC):
    name = "base"
    version = PARSER_VERSION
    extensions: set[str] = set()

    def supports(self, extension: str) -> bool:
        return extension.lower() in self.extensions

    @abstractmethod
    def parse(self, path: Path, *, mime_type: str, title: str) -> DocumentIR:
        raise NotImplementedError


class TextParser(DocumentParser):
    name = "text"
    extensions = {"txt", "md", "markdown"}

    def parse(self, path: Path, *, mime_type: str, title: str) -> DocumentIR:
        data = path.read_bytes()
        match = from_bytes(data).best()
        if match is None:
            raise ValueError("无法识别文本文件编码。")
        text = str(match)
        if path.suffix.lower() == ".txt":
            blocks = []
            for paragraph in re.split(r"\n\s*\n", text):
                paragraph = paragraph.strip()
                if paragraph:
                    blocks.append(BlockIR(
                        id=f"p1-b{len(blocks) + 1}", type="paragraph", text=paragraph,
                        page=1, metadata={"paragraph": len(blocks) + 1},
                    ))
            page = PageIR(page_number=1, blocks=blocks, metadata={"paginated": False})
        else:
            page = markdown_page(text, 1)
            page.metadata["paginated"] = False
        return DocumentIR(title=title, mime_type=mime_type, parser=self.name, parser_version=self.version, pages=[page])


class DocxParser(DocumentParser):
    name = "docx"
    extensions = {"docx"}

    def parse(self, path: Path, *, mime_type: str, title: str) -> DocumentIR:
        from docx import Document as DocxDocument
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = DocxDocument(path)
        blocks: list[BlockIR] = []
        headings: list[str] = []
        for item in document.iter_inner_content():
            text = ""
            block_type = "paragraph"
            metadata = {"paragraph": len(blocks) + 1}
            if isinstance(item, Paragraph):
                text = item.text.strip()
                style = str(item.style.name or "") if item.style else ""
                match = re.search(r"Heading\s+(\d+)|标题\s*(\d+)", style, re.IGNORECASE)
                if match and text:
                    level = int(match.group(1) or match.group(2))
                    headings = headings[: level - 1]
                    headings.append(text)
                    block_type = "heading"
                    metadata["level"] = level
                elif style.lower().startswith("list"):
                    block_type = "list"
            elif isinstance(item, Table):
                rows = [[cell.text.strip().replace("\n", " ") for cell in row.cells] for row in item.rows]
                text = "\n".join(" | ".join(row) for row in rows if any(row))
                block_type = "table"
                metadata["rows"] = len(rows)
            if text:
                blocks.append(BlockIR(
                    id=f"p1-b{len(blocks) + 1}", type=block_type, text=text,
                    page=1, heading_path=list(headings), metadata=metadata,
                ))
        page = PageIR(page_number=1, blocks=blocks, metadata={"paginated": False})
        return DocumentIR(title=title, mime_type=mime_type, parser=self.name, parser_version=self.version, pages=[page])


class PdfParser(DocumentParser):
    name = "pymupdf"
    extensions = {"pdf"}

    def parse(self, path: Path, *, mime_type: str, title: str) -> DocumentIR:
        import fitz

        pages: list[PageIR] = []
        all_font_sizes: list[float] = []
        raw_pages = []
        with fitz.open(path) as pdf:
            if pdf.needs_pass:
                raise ValueError("暂不支持加密 PDF。")
            for page in pdf:
                raw = page.get_text("dict", sort=True)
                raw_pages.append(raw)
                for raw_block in raw.get("blocks", []):
                    if raw_block.get("type") != 0:
                        continue
                    for line in raw_block.get("lines", []):
                        for span in line.get("spans", []):
                            if str(span.get("text") or "").strip():
                                all_font_sizes.append(float(span.get("size") or 0))
        body_size = statistics.median(all_font_sizes) if all_font_sizes else 10.0
        headings: list[str] = []
        for page_index, raw in enumerate(raw_pages):
            page_number = page_index + 1
            blocks: list[BlockIR] = []
            for raw_block in raw.get("blocks", []):
                if raw_block.get("type") != 0:
                    continue
                spans = [span for line in raw_block.get("lines", []) for span in line.get("spans", [])]
                lines = ["".join(str(span.get("text") or "") for span in line.get("spans", [])).strip() for line in raw_block.get("lines", [])]
                text = "\n".join(line for line in lines if line).strip()
                if not text:
                    continue
                max_size = max((float(span.get("size") or 0) for span in spans), default=body_size)
                ratio = max_size / max(body_size, 1)
                is_heading = len(text) <= 120 and ratio >= 1.35
                block_type = "heading" if is_heading else "paragraph"
                metadata = {"paragraph": len(blocks) + 1, "font_size": round(max_size, 2)}
                if is_heading:
                    level = 1 if ratio >= 2 else 2 if ratio >= 1.6 else 3
                    headings = headings[: level - 1]
                    headings.append(text.replace("\n", " "))
                    metadata["level"] = level
                blocks.append(BlockIR(
                    id=f"p{page_number}-b{len(blocks) + 1}", type=block_type, text=text,
                    page=page_number, heading_path=list(headings),
                    bbox=[round(float(value), 2) for value in raw_block.get("bbox", [])], metadata=metadata,
                ))
            pages.append(PageIR(page_number=page_number, blocks=blocks, extraction_method="native", metadata={"paginated": True}))
        return DocumentIR(title=title, mime_type=mime_type, parser=self.name, parser_version=self.version, pages=pages)


def get_parser(extension: str) -> DocumentParser:
    for parser in (TextParser(), DocxParser(), PdfParser()):
        if parser.supports(extension):
            return parser
    raise ValueError(f"不支持的文档类型：{extension}")
