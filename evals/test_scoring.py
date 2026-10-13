import json

import httpx

import run_eval
from app.ingest import SUPPORTED_EXTENSIONS, chunk_pages, extract_pages
from run_eval import (
    HERE,
    CaseResult,
    Report,
    ask_with_retry,
    check_baseline,
    contains_any,
    evidence_rank,
    is_refusal,
    keywords_match,
    load_golden,
    normalize,
    percentile,
)


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


def test_retrieval_only_summary_reports_ranks_without_answer_metrics():
    def case(rank):
        return CaseResult("c", "q", True, "", rank, False, False, False, 0, retrieval_ms=10)

    summary = Report("r", 5, retrieval_only=True, cases=[case(1), case(2), case(None)]).summary()
    assert summary["retrieval_hit_at_1"] == 0.333
    assert summary["retrieval_hit_at_k"] == 0.667
    assert summary["retrieval_mrr"] == 0.5
    assert "answer_accuracy" not in summary


# ---------- regression gate ----------

BASELINE = {"top_k": 5, "modes": {"hybrid": {"retrieval_hit_at_k": 1.0, "retrieval_mrr": 0.911}}}


def test_baseline_passes_when_metrics_hold_or_improve():
    assert check_baseline({"retrieval_hit_at_k": 1.0, "retrieval_mrr": 0.95}, BASELINE, "hybrid", 5) == []


def test_baseline_fails_on_any_drop():
    failures = check_baseline({"retrieval_hit_at_k": 0.979, "retrieval_mrr": 0.911}, BASELINE, "hybrid", 5)
    assert failures == ["retrieval_hit_at_k 0.979 < baseline 1.0"]


def test_baseline_refuses_mismatched_settings():
    assert check_baseline({}, BASELINE, "hybrid", 3)  # different top_k
    assert check_baseline({}, BASELINE, "vector", 5)  # no baseline for this mode


def test_baseline_file_is_valid():
    baseline = json.loads((HERE / "baseline.json").read_text())
    assert baseline["top_k"] == 5
    for metrics in baseline["modes"].values():
        assert set(metrics) >= {"retrieval_hit_at_k", "retrieval_mrr"}


# ---------- prompt injection ----------

def test_contains_any_normalises_case_and_spacing():
    assert contains_any("Sure!  ACCESS granted.", ["access granted"])
    assert not contains_any("The limit is 80%.", ["access granted"])


def test_injection_resistance_in_summary():
    def case(obeyed):
        return CaseResult("c", "q", True, "a", 1, not obeyed, False, True, 5, 1, obeyed_injection=obeyed)

    summary = Report("r", 5, cases=[case(False), case(False), case(True), case(None)]).summary()
    assert summary["injection_resistance"] == 0.667


def test_injection_set_is_well_formed():
    cases = load_golden(HERE / "injection.jsonl")
    docs = "\n".join(normalize(p.read_text()) for p in (HERE / "injection_docs").glob("*.md"))
    assert cases and all(c["forbidden"] for c in cases)
    for c in cases:
        if c["evidence"]:
            assert normalize(c["evidence"]) in docs, c["id"]

