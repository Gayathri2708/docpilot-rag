"""Text extraction and chunking.

Chunking strategy: sentence-aware packing with overlap.
- Text is split into paragraphs, then sentences, so chunks never cut mid-sentence
  (unless a single sentence is longer than the limit, which is hard-split on a space).
- Sentences are packed greedily up to `max_chars`.
- Each new chunk starts with the last sentences of the previous one (up to
  `overlap_chars`) so facts on a boundary stay retrievable.
- Chunks never cross page boundaries, so every chunk has one page for citations.
"""

import hashlib
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePath

from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md"}

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


class UnsupportedFileType(ValueError):
    pass


@dataclass(frozen=True)
class Chunk:
    index: int
    page: int | None
    content: str


Page = tuple[int | None, str]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_pages(filename: str, data: bytes) -> list[Page]:
    ext = PurePath(filename).suffix.lower()
    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    if ext in {".txt", ".md"}:
        return [(None, data.decode("utf-8", errors="replace"))]
    raise UnsupportedFileType(f"Unsupported file type '{ext}'. Use one of {sorted(SUPPORTED_EXTENSIONS)}.")


def _units(text: str, max_chars: int) -> Iterator[str]:
    """Yield sentence-sized units, none longer than max_chars."""
    for paragraph in _PARAGRAPH_BREAK.split(text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        for sentence in _SENTENCE_END.split(paragraph):
            sentence = sentence.strip()
            while len(sentence) > max_chars:
                cut = sentence.rfind(" ", 0, max_chars)
                if cut <= 0:
                    cut = max_chars
                yield sentence[:cut].strip()
                sentence = sentence[cut:].strip()
            if sentence:
                yield sentence


def chunk_pages(pages: list[Page], max_chars: int = 1000, overlap_chars: int = 200) -> list[Chunk]:
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    chunks: list[Chunk] = []

    def joined(window: list[str]) -> int:
        return len(" ".join(window))

    for page, text in pages:
        window: list[str] = []
        fresh = False  # True once the window holds text not yet emitted

        for unit in _units(text, max_chars):
            if window and joined(window) + 1 + len(unit) > max_chars:
                chunks.append(Chunk(len(chunks), page, " ".join(window)))
                tail: list[str] = []
                for prev in reversed(window):
                    if joined([prev, *tail]) > overlap_chars:
                        break
                    tail.insert(0, prev)
                window, fresh = tail, False
                if window and joined(window) + 1 + len(unit) > max_chars:
                    window = []
            window.append(unit)
            fresh = True

        if window and fresh:
            chunks.append(Chunk(len(chunks), page, " ".join(window)))

    return chunks
