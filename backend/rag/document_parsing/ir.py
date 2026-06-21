from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class BlockIR:
    id: str
    type: str
    text: str
    page: int
    heading_path: list[str] = field(default_factory=list)
    bbox: list[float] = field(default_factory=list)
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PageIR:
    page_number: int
    blocks: list[BlockIR] = field(default_factory=list)
    extraction_method: str = "native"
    markdown: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(block.text.strip() for block in self.blocks if block.text.strip()).strip()


@dataclass
class DocumentIR:
    title: str
    mime_type: str
    parser: str
    parser_version: str
    pages: list[PageIR] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text).strip()


def load_document_ir(parse_run) -> DocumentIR:
    pages = []
    for page in parse_run.pages.order_by("page_number"):
        blocks = [
            BlockIR(
                id=str(item.get("id") or f"p{page.page_number}-b{index + 1}"),
                type=str(item.get("type") or "paragraph"),
                text=str(item.get("text") or ""),
                page=int(item.get("page") or page.page_number),
                heading_path=list(item.get("heading_path") or []),
                bbox=list(item.get("bbox") or []),
                confidence=item.get("confidence"),
                metadata=dict(item.get("metadata") or {}),
            )
            for index, item in enumerate(page.blocks or [])
        ]
        pages.append(PageIR(
            page_number=page.page_number,
            blocks=blocks,
            extraction_method=page.extraction_method,
            markdown=page.markdown,
            metadata=dict(page.metrics or {}),
        ))
    return DocumentIR(
        title=parse_run.document.filename,
        mime_type=parse_run.document.mime_type,
        parser=parse_run.parser,
        parser_version=parse_run.parser_version,
        pages=pages,
        metadata={"parse_run_id": parse_run.id},
    )
