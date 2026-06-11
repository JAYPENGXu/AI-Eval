import re

from .base import BaseChunker, ChunkItem, ChunkOptions, make_chunk, rough_token_count


SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")


def split_sentences(text: str) -> list[str]:
    sentences = [match.group(0).strip() for match in SENTENCE_RE.finditer(text)]
    return [sentence for sentence in sentences if sentence]


class SentenceChunker(BaseChunker):
    method = "sentence"
    label = "句子切片"

    def split(self, text: str, options: ChunkOptions) -> list[ChunkItem]:
        sentences = split_sentences(text)
        chunks: list[ChunkItem] = []
        current: list[str] = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = rough_token_count(sentence)
            if current and current_tokens + sentence_tokens > options.chunk_size:
                chunks.append(make_chunk(len(chunks), "\n".join(current), self.method))
                overlap = []
                overlap_tokens = 0
                for item in reversed(current):
                    item_tokens = rough_token_count(item)
                    if overlap_tokens + item_tokens > options.chunk_overlap:
                        break
                    overlap.insert(0, item)
                    overlap_tokens += item_tokens
                current = overlap
                current_tokens = overlap_tokens
            current.append(sentence)
            current_tokens += sentence_tokens

        if current:
            chunks.append(make_chunk(len(chunks), "\n".join(current), self.method))
        return chunks
