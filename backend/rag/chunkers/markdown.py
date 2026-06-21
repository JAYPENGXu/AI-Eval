from .base import BaseChunker, ChunkItem, ChunkOptions, flatten_document, make_chunk, provenance


class MarkdownChunker(BaseChunker):
    method = "markdown"
    label = "Markdown 切片"

    def split(self, document, options: ChunkOptions) -> list[ChunkItem]:
        document_ir, _, spans = flatten_document(document)
        chunks: list[ChunkItem] = []
        for span in spans:
            text = span.block.text.strip()
            if not text:
                continue
            metadata = provenance(document_ir, spans, span.start, span.end)
            metadata["block_type"] = span.block.type
            chunks.append(make_chunk(len(chunks), text, self.method, **metadata))
        return chunks
