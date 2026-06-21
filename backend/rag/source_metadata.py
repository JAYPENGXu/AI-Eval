from __future__ import annotations


def source_location(metadata: dict | None) -> dict:
    metadata = metadata or {}
    page_start = metadata.get("page_start")
    page_end = metadata.get("page_end")
    heading_path = list(metadata.get("heading_path") or [])
    paragraph_start = metadata.get("paragraph_start")
    paragraph_end = metadata.get("paragraph_end")
    parts = []
    if page_start:
        parts.append(f"第 {page_start} 页" if not page_end or page_end == page_start else f"第 {page_start}-{page_end} 页")
    if heading_path:
        parts.append(" / ".join(str(item) for item in heading_path))
    if paragraph_start:
        parts.append(f"段落 {paragraph_start}" if not paragraph_end or paragraph_end == paragraph_start else f"段落 {paragraph_start}-{paragraph_end}")
    return {
        "page_start": page_start,
        "page_end": page_end,
        "page_numbers": metadata.get("page_numbers") or [],
        "heading_path": heading_path,
        "paragraph_start": paragraph_start,
        "paragraph_end": paragraph_end,
        "label": " · ".join(parts),
    }
