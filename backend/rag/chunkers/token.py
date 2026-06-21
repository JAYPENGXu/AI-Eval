from .base import BaseChunker, ChunkItem, ChunkOptions, flatten_document, make_chunk, provenance


class TokenChunker(BaseChunker):
    method = "token"
    label = "Token 切片"

    def split(self, document, options: ChunkOptions) -> list[ChunkItem]:
        document_ir, text, spans = flatten_document(document)
        chars_per_token = 2
        chunk_chars = max(options.chunk_size * chars_per_token, 100)
        overlap_chars = max(options.chunk_overlap * chars_per_token, 0)
        step = max(chunk_chars - overlap_chars, 1)
        chunks: list[ChunkItem] = []
        for start in range(0, len(text), step):
            raw = text[start:start + chunk_chars]
            content = raw.strip()
            if not content:
                continue
            leading = len(raw) - len(raw.lstrip())
            chunk_start = start + leading
            chunk_end = chunk_start + len(content)
            chunks.append(make_chunk(
                len(chunks), content, self.method,
                start=chunk_start, end=chunk_end,
                **provenance(document_ir, spans, chunk_start, chunk_end),
            ))
            if start + chunk_chars >= len(text):
                break
        return chunks
