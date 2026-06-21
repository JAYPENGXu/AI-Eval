from .base import BaseChunker, ChunkItem, ChunkOptions, flatten_document, make_chunk, provenance
from .sentence import split_sentences_with_offsets


class SentenceWindowChunker(BaseChunker):
    method = "sentence_window"
    label = "句子窗口切片"

    def split(self, document, options: ChunkOptions) -> list[ChunkItem]:
        document_ir, text, spans = flatten_document(document)
        sentences = split_sentences_with_offsets(text)
        window = max(options.window_size, 1)
        chunks: list[ChunkItem] = []
        for index, sentence in enumerate(sentences):
            start_index = max(0, index - window)
            end_index = min(len(sentences), index + window + 1)
            selected = sentences[start_index:end_index]
            chunks.append(make_chunk(
                len(chunks), "\n".join(item[0] for item in selected), self.method,
                center_sentence=index, window_size=window,
                **provenance(document_ir, spans, selected[0][1], selected[-1][2]),
            ))
        return chunks
