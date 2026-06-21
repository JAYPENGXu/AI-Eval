import math
from collections import Counter

from .base import BaseChunker, ChunkItem, ChunkOptions, flatten_document, make_chunk, provenance, rough_token_count
from .sentence import split_sentences_with_offsets


def char_vector(text: str) -> Counter:
    return Counter(char for char in text if not char.isspace())


def cosine(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0
    common = set(left) & set(right)
    dot = sum(left[key] * right[key] for key in common)
    norm_left = math.sqrt(sum(value * value for value in left.values()))
    norm_right = math.sqrt(sum(value * value for value in right.values()))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0


class SemanticChunker(BaseChunker):
    method = "semantic"
    label = "语义切片"

    def split(self, document, options: ChunkOptions) -> list[ChunkItem]:
        document_ir, text, spans = flatten_document(document)
        sentences = split_sentences_with_offsets(text)
        if not sentences:
            return []
        chunks: list[ChunkItem] = []
        current = [sentences[0]]
        threshold = options.semantic_threshold

        def append_current(reason=None):
            start, end = current[0][1], current[-1][2]
            metadata = provenance(document_ir, spans, start, end)
            if reason:
                metadata["split_reason"] = reason
            chunks.append(make_chunk(len(chunks), "\n".join(item[0] for item in current), self.method, **metadata))

        for sentence in sentences[1:]:
            current_text = "\n".join(item[0] for item in current)
            similarity = cosine(char_vector(current_text), char_vector(sentence[0]))
            would_exceed = rough_token_count(current_text + sentence[0]) > options.chunk_size
            if similarity < threshold or would_exceed:
                append_current("semantic_boundary" if similarity < threshold else "chunk_size")
                current = [sentence]
            else:
                current.append(sentence)
        append_current()
        return chunks
