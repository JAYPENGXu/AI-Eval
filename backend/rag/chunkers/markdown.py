import re

from .base import BaseChunker, ChunkItem, ChunkOptions, make_chunk


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


class MarkdownChunker(BaseChunker):
    method = "markdown"
    label = "Markdown 切片"

    def split(self, text: str, options: ChunkOptions) -> list[ChunkItem]:
        blocks = []
        current_title = "文档开始"
        current_lines: list[str] = []

        for line in text.splitlines():
            match = HEADING_RE.match(line.strip())
            if match and current_lines:
                blocks.append((current_title, "\n".join(current_lines)))
                current_title = match.group(2).strip()
                current_lines = [line]
            else:
                if match:
                    current_title = match.group(2).strip()
                current_lines.append(line)

        if current_lines:
            blocks.append((current_title, "\n".join(current_lines)))

        chunks = []
        for title, content in blocks:
            if content.strip():
                chunks.append(make_chunk(len(chunks), content, self.method, heading=title))
        return chunks
