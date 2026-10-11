import pytest

from app.ingest import UnsupportedFileType, chunk_pages, extract_pages

SENTENCE = "Employees receive twenty four days of paid leave every calendar year."  # 70 chars


def test_chunks_respect_max_size():
    text = " ".join([SENTENCE] * 50)
    chunks = chunk_pages([(None, text)], max_chars=300, overlap_chars=80)
    assert len(chunks) > 1
    assert all(len(c.content) <= 300 for c in chunks)


def test_consecutive_chunks_overlap():
    sentences = [f"Fact number {i} is stated in this sentence." for i in range(40)]
    chunks = chunk_pages([(None, " ".join(sentences))], max_chars=200, overlap_chars=60)
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        last_sentence_of_prev = prev.content.split(". ")[-1]
        assert last_sentence_of_prev in nxt.content


def test_no_text_is_lost():
    sentences = [f"Unique sentence {i} goes here." for i in range(30)]
    chunks = chunk_pages([(None, " ".join(sentences))], max_chars=150, overlap_chars=40)
    combined = " ".join(c.content for c in chunks)
    for s in sentences:
        assert s in combined


def test_chunks_keep_their_page_and_never_span_pages():
    pages = [(1, "Page one talks about leave."), (2, "Page two talks about expenses.")]
    chunks = chunk_pages(pages, max_chars=500, overlap_chars=50)
    assert [(c.page, c.content) for c in chunks] == [
        (1, "Page one talks about leave."),
        (2, "Page two talks about expenses."),
    ]


def test_indices_are_sequential_across_pages():
    pages = [(1, " ".join([SENTENCE] * 10)), (2, " ".join([SENTENCE] * 10))]
    chunks = chunk_pages(pages, max_chars=200, overlap_chars=50)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_very_long_sentence_is_hard_split():
    long_sentence = "word " * 500
    chunks = chunk_pages([(None, long_sentence)], max_chars=100, overlap_chars=20)
    assert all(len(c.content) <= 100 for c in chunks)
    assert len(chunks) >= 25


def test_empty_and_whitespace_pages_produce_no_chunks():
    assert chunk_pages([(1, ""), (2, "   \n\n  ")]) == []


def test_overlap_must_be_smaller_than_max():
    with pytest.raises(ValueError):
        chunk_pages([(None, "text")], max_chars=100, overlap_chars=100)


def test_markdown_is_read_as_single_page():
    pages = extract_pages("notes.md", b"# Title\n\nSome text.")
    assert pages == [(None, "# Title\n\nSome text.")]


def test_unsupported_extension_is_rejected():
    with pytest.raises(UnsupportedFileType):
        extract_pages("image.png", b"\x89PNG")
