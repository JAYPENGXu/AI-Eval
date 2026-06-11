from .base import BaseChunker
from .markdown import MarkdownChunker
from .semantic import SemanticChunker
from .sentence import SentenceChunker
from .sentence_window import SentenceWindowChunker
from .token import TokenChunker


CHUNKERS: dict[str, type[BaseChunker]] = {
    "sentence": SentenceChunker,
    "token": TokenChunker,
    "sentence_window": SentenceWindowChunker,
    "semantic": SemanticChunker,
    "markdown": MarkdownChunker,
}


def get_chunker(method: str) -> BaseChunker:
    chunker_cls = CHUNKERS.get(method) or CHUNKERS["sentence"]
    return chunker_cls()


def list_chunk_methods() -> list[dict]:
    return [
        {"value": value, "label": cls.label, "default": value == "sentence"}
        for value, cls in CHUNKERS.items()
    ]
