from dataclasses import dataclass, field
from typing import Any


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


class BaseChunker:
    method = "base"
    label = "Base"

    def split(self, text: str, options: ChunkOptions) -> list[ChunkItem]:
        raise NotImplementedError


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
