from .base import BaseChunker, ChunkItem, ChunkOptions, make_chunk


class TokenChunker(BaseChunker):
    method = "token"
    label = "Token 切片"

    def split(self, text: str, options: ChunkOptions) -> list[ChunkItem]:
        chars_per_token = 2
        chunk_chars = max(options.chunk_size * chars_per_token, 100)
        overlap_chars = max(options.chunk_overlap * chars_per_token, 0)
        step = max(chunk_chars - overlap_chars, 1)
        chunks: list[ChunkItem] = []

        for start in range(0, len(text), step):
            content = text[start:start + chunk_chars].strip()
            if not content:
                continue
            chunks.append(
                make_chunk(
                    len(chunks),
                    content,
                    self.method,
                    start=start,
                    end=start + len(content),
                )
            )
            if start + chunk_chars >= len(text):
                break
        return chunks
