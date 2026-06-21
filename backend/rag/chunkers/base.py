from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rag.document_parsing.ir import BlockIR, DocumentIR, PageIR


@dataclass
class ChunkOptions:
    chunk_size: int = 800
    chunk_overlap: int = 100
    window_size: int = 1
    semantic_threshold: float = 0.72


@dataclass
class ChunkItem:
    index: int
    content: str
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceSpan:
    start: int
    end: int
    block: BlockIR
    paginated: bool = True


class BaseChunker:
    method = "base"
    label = "Base"

    def split(self, document: DocumentIR | str, options: ChunkOptions) -> list[ChunkItem]:
        raise NotImplementedError


def coerce_document(value: DocumentIR | str) -> DocumentIR:
    if isinstance(value, DocumentIR):
        return value
    block = BlockIR(id="p1-b1", type="paragraph", text=str(value or ""), page=1, metadata={"paragraph": 1})
    return DocumentIR(
        title="", mime_type="text/plain", parser="legacy_text", parser_version="1",
        pages=[PageIR(page_number=1, blocks=[block], metadata={"paginated": False})],
    )


def flatten_document(value: DocumentIR | str) -> tuple[DocumentIR, str, list[SourceSpan]]:
    document = coerce_document(value)
    parts: list[str] = []
    spans: list[SourceSpan] = []
    cursor = 0
    for page in document.pages:
        for block in page.blocks:
            text = block.text.strip()
            if not text:
                continue
            if parts:
                parts.append("\n\n")
                cursor += 2
            start = cursor
            parts.append(text)
            cursor += len(text)
            spans.append(SourceSpan(start=start, end=cursor, block=block, paginated=page.metadata.get("paginated", True)))
    return document, "".join(parts), spans


def provenance(document: DocumentIR, spans: list[SourceSpan], start: int, end: int) -> dict[str, Any]:
    selected = [span for span in spans if span.start < end and span.end > start]
    if not selected and spans:
        selected = [min(spans, key=lambda span: abs(span.start - start))]
    pages = sorted({span.block.page for span in selected})
    block_ids = [span.block.id for span in selected]
    paragraphs = [
        int(span.block.metadata["paragraph"])
        for span in selected
        if str(span.block.metadata.get("paragraph", "")).isdigit()
    ]
    heading_path = next((span.block.heading_path for span in selected if span.block.heading_path), [])
    paginated = any(span.paginated for span in selected)
    metadata: dict[str, Any] = {
        "page_numbers": pages,
        "page_start": pages[0] if pages and paginated else None,
        "page_end": pages[-1] if pages and paginated else None,
        "heading_path": list(heading_path),
        "block_ids": block_ids,
        "paragraph_start": min(paragraphs) if paragraphs else None,
        "paragraph_end": max(paragraphs) if paragraphs else None,
        "parser": document.parser,
        "parser_version": document.parser_version,
        "parse_run_id": document.metadata.get("parse_run_id"),
        "paginated": paginated,
    }
    return metadata


def rough_token_count(text: str) -> int:
    ascii_words = len([part for part in text.replace("\n", " ").split(" ") if part.strip()])
    non_ascii = sum(1 for char in text if ord(char) > 127)
    return max(ascii_words + non_ascii // 2, 1)


def make_chunk(index: int, content: str, method: str, **metadata) -> ChunkItem:
    content = content.strip()
    return ChunkItem(
        index=index,
        content=content,
        token_count=rough_token_count(content),
        metadata={"method": method, **metadata},
    )
