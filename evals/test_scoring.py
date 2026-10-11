from run_eval import HERE, evidence_rank, is_refusal, keywords_match, load_golden, percentile


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


def test_golden_evidence_exists_in_sample_doc():
    """Guards the golden set itself: every evidence string must really be in the document."""
    doc = (HERE / "sample_docs" / "northwind_handbook.md").read_text(encoding="utf-8")
    flat = " ".join(doc.split()).lower()
    for case in load_golden(HERE / "golden.jsonl"):
        if case["answerable"]:
            assert " ".join(case["evidence"].split()).lower() in flat, case["id"]
