import re

from .base import BaseChunker, ChunkItem, ChunkOptions, flatten_document, make_chunk, provenance, rough_token_count


SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")


def split_sentences(text: str) -> list[str]:
    return [sentence for sentence, _, _ in split_sentences_with_offsets(text)]


def split_sentences_with_offsets(text: str) -> list[tuple[str, int, int]]:
    rows = []
    for match in SENTENCE_RE.finditer(text):
        raw = match.group(0)
        value = raw.strip()
        if value:
            leading = len(raw) - len(raw.lstrip())
            start = match.start() + leading
            rows.append((value, start, start + len(value)))
    return rows


class SentenceChunker(BaseChunker):
    method = "sentence"
    label = "句子切片"

    def split(self, document, options: ChunkOptions) -> list[ChunkItem]:
        document_ir, text, spans = flatten_document(document)
        sentences = split_sentences_with_offsets(text)
        chunks: list[ChunkItem] = []
        current: list[tuple[str, int, int]] = []
        current_tokens = 0

        def append_current() -> None:
            if not current:
                return
            start, end = current[0][1], current[-1][2]
            chunks.append(make_chunk(
                len(chunks), "\n".join(item[0] for item in current), self.method,
                **provenance(document_ir, spans, start, end),
            ))

        for sentence in sentences:
            sentence_tokens = rough_token_count(sentence[0])
            if current and current_tokens + sentence_tokens > options.chunk_size:
                append_current()
                overlap = []
                overlap_tokens = 0
                for item in reversed(current):
                    item_tokens = rough_token_count(item[0])
                    if overlap_tokens + item_tokens > options.chunk_overlap:
                        break
                    overlap.insert(0, item)
                    overlap_tokens += item_tokens
                current = overlap
                current_tokens = overlap_tokens
            current.append(sentence)
            current_tokens += sentence_tokens
        append_current()
        return chunks
