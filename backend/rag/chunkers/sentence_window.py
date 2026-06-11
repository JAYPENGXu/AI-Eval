from .base import BaseChunker, ChunkItem, ChunkOptions, make_chunk
from .sentence import split_sentences


class SentenceWindowChunker(BaseChunker):
    method = "sentence_window"
    label = "句子窗口切片"

    def split(self, text: str, options: ChunkOptions) -> list[ChunkItem]:
        sentences = split_sentences(text)
        window = max(options.window_size, 1)
        chunks: list[ChunkItem] = []

        for index, sentence in enumerate(sentences):
            start = max(0, index - window)
            end = min(len(sentences), index + window + 1)
            content = "\n".join(sentences[start:end])
            chunks.append(
                make_chunk(
                    len(chunks),
                    content,
                    self.method,
                    center_sentence=index,
                    window_size=window,
                )
            )
        return chunks
