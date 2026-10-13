import httpx

import run_eval
from app.ingest import SUPPORTED_EXTENSIONS, chunk_pages, extract_pages
from run_eval import HERE, ask_with_retry, evidence_rank, is_refusal, keywords_match, load_golden, normalize, percentile


def test_keywords_require_every_group():
    assert keywords_match("Office days are Tuesday, Wednesday and Thursday [1].", ["tuesday", "thursday"])
    assert not keywords_match("Office days are Tuesday [1].", ["tuesday", "thursday"])


def test_keyword_alternatives():
    assert keywords_match("Core hours are 11 AM to 4 PM.", [["11:00", "11 am"], ["16:00", "4 pm"]])


def test_refusal_detection_handles_curly_apostrophe():
    assert is_refusal("I couldn’t find this in the uploaded documents.")
    assert not is_refusal("It is 24 days [1].")


def test_evidence_rank_ignores_case_and_whitespace():
    chunks = ["Unrelated text.", "Every employee receives 24 DAYS of paid\nleave per calendar year."]
    assert evidence_rank("24 days of paid leave per calendar year", chunks) == 2
    assert evidence_rank("not present", chunks) is None


def test_percentile():
    assert percentile([100, 200, 300, 400, 500], 50) == 300
    assert percentile([], 95) == 0.0


def test_golden_evidence_exists_in_exactly_one_sample_doc():
    """Guards the golden set itself: every evidence string must survive extraction and chunking
    (so retrieval can find it) and appear in only one document (so a hit means the right source)."""
    chunks_by_doc = {}
    for path in sorted((HERE / "sample_docs").iterdir()):
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            pages = extract_pages(path.name, path.read_bytes())
            chunks_by_doc[path.name] = [normalize(c.content) for c in chunk_pages(pages)]
    assert len(chunks_by_doc) >= 5

    for case in load_golden(HERE / "golden.jsonl"):
        if case["answerable"]:
            evidence = normalize(case["evidence"])
            docs = [name for name, chunks in chunks_by_doc.items() if any(evidence in c for c in chunks)]
            assert len(docs) == 1, (case["id"], docs)


def test_ask_retries_rate_limits_with_backoff(monkeypatch):
    statuses = iter([429, 502, 200])
    waits = []
    monkeypatch.setattr(run_eval.time, "sleep", waits.append)
    transport = httpx.MockTransport(lambda request: httpx.Response(next(statuses), json={"answer": "ok"}))
    with httpx.Client(transport=transport, base_url="http://test") as client:
        body, _ = ask_with_retry(client, "q", 5)
    assert body == {"answer": "ok"}
    assert waits == [15, 30]
