import math
from collections import Counter

from .base import BaseChunker, ChunkItem, ChunkOptions, make_chunk, rough_token_count
from .sentence import split_sentences


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

    def split(self, text: str, options: ChunkOptions) -> list[ChunkItem]:
        sentences = split_sentences(text)
        if not sentences:
            return []

        chunks: list[ChunkItem] = []
        current = [sentences[0]]
        threshold = options.semantic_threshold

        for sentence in sentences[1:]:
            current_text = "\n".join(current)
            similarity = cosine(char_vector(current_text), char_vector(sentence))
            would_exceed = rough_token_count(current_text + sentence) > options.chunk_size
            if current and (similarity < threshold or would_exceed):
                chunks.append(
                    make_chunk(
                        len(chunks),
                        current_text,
                        self.method,
                        split_reason="semantic_boundary" if similarity < threshold else "chunk_size",
                    )
                )
                current = [sentence]
            else:
                current.append(sentence)

        if current:
            chunks.append(make_chunk(len(chunks), "\n".join(current), self.method))
        return chunks
