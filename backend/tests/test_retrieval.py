"""Fusion and search orchestration, with the database, embedder and reranker stubbed out."""

import pytest

from app import retrieval
from app.retrieval import Hit, rrf_fuse


def hit(chunk_id: int, score: float = 0.7) -> Hit:
    return Hit(chunk_id, "d1", "doc.md", None, chunk_id, f"chunk {chunk_id}", score)


# ---------- rrf_fuse ----------

def test_rrf_rewards_agreement_between_retrievers():
    # 3 is only 2nd and 3rd, but appears in both lists, so it beats each list's single winner.
    assert rrf_fuse([[1, 3, 4], [2, 5, 3]])[0] == 3


def test_rrf_scores_match_formula():
    fused = rrf_fuse([[10, 20], [20]], k=60)
    assert fused == [20, 10]  # 1/62 + 1/61 > 1/61


def test_rrf_includes_items_from_either_list():
    assert set(rrf_fuse([[1, 2], [3]])) == {1, 2, 3}


def test_rrf_ties_keep_first_ranking_order():
    # 1 and 2 are both rank 1 in one list: identical scores, first list wins the tie.
    assert rrf_fuse([[1], [2]]) == [1, 2]


def test_rrf_single_list_preserves_order():
    assert rrf_fuse([[5, 3, 9]]) == [5, 3, 9]


def test_rrf_empty():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_rrf_small_k_sharpens_rank_differences():
    # 1 is ranked 1st and 10th; 2 is ranked 3rd twice. A small k rewards the single top rank,
    # the standard k=60 rewards consistent agreement.
    rankings = [[1, 10, 2], [11, 12, 2, 13, 14, 15, 16, 17, 18, 1]]
    assert rrf_fuse(rankings, k=1)[0] == 1
    assert rrf_fuse(rankings, k=60)[0] == 2


# ---------- search ----------

@pytest.fixture
def stub_backends(monkeypatch):
    """Vector search returns 1, 2, 3; keyword search returns 3, 4. Records which queries ran."""
    calls = []

    def fake_fetch(sql, params):
        kind = "keyword" if sql is retrieval._KEYWORD_SQL else "vector"
        calls.append((kind, params["n"]))
        ids = [3, 4] if kind == "keyword" else [1, 2, 3]
        return [hit(i, score=1 - i / 10) for i in ids][: params["n"]]

    monkeypatch.setattr(retrieval, "_fetch", fake_fetch)
    monkeypatch.setattr(retrieval, "embed_query", lambda q: [0.0])
    return calls


def test_vector_mode_skips_keyword_search(stub_backends):
    hits = retrieval.search("q", groups=["all"], k=2, mode="vector", rerank=False)
    assert [h.chunk_id for h in hits] == [1, 2]
    assert stub_backends == [("vector", 2)]  # no wider pool needed


def test_hybrid_mode_fuses_both_retrievers(stub_backends):
    hits = retrieval.search("q", groups=["all"], k=4, mode="hybrid", rerank=False)
    # 3 is in both lists, so it rises to the top; 4 comes only from keyword search.
    assert [h.chunk_id for h in hits] == [3, 1, 2, 4]
    assert {kind for kind, _ in stub_backends} == {"vector", "keyword"}
    assert all(n == 20 for _, n in stub_backends)  # candidate pool, not k


def test_hits_keep_cosine_score_after_fusion(stub_backends):
    hits = retrieval.search("q", groups=["all"], k=4, mode="hybrid", rerank=False)
    assert {h.chunk_id: h.score for h in hits} == {1: 0.9, 2: 0.8, 3: 0.7, 4: 0.6}


def test_rerank_reorders_candidates(stub_backends, monkeypatch):
    # Reranker prefers higher chunk ids.
    monkeypatch.setattr(
        retrieval, "rerank_scores", lambda q, passages: [float(p.split()[-1]) for p in passages]
    )
    hits = retrieval.search("q", groups=["all"], k=2, mode="hybrid", rerank=True)
    assert [h.chunk_id for h in hits] == [4, 3]


def test_settings_supply_defaults(stub_backends, monkeypatch):
    monkeypatch.setattr(retrieval.settings, "retrieval_mode", "hybrid")
    monkeypatch.setattr(retrieval.settings, "rerank", False)
    retrieval.search("q", groups=["all"], k=2)
    assert ("keyword", 20) in stub_backends


# ---------- access control ----------

def test_both_retrievers_filter_by_access_group_in_sql():
    for sql in (retrieval._VECTOR_SQL, retrieval._KEYWORD_SQL):
        assert "d.access_group = ANY(%(groups)s)" in sql


def test_search_passes_caller_groups_to_every_query(monkeypatch):
    seen = []
    monkeypatch.setattr(retrieval, "_fetch", lambda sql, params: seen.append(params["groups"]) or [])
    monkeypatch.setattr(retrieval, "embed_query", lambda q: [0.0])
    retrieval.search("q", k=5, groups=("all", "engineering"), mode="hybrid", rerank=False)
    assert seen == [["all", "engineering"], ["all", "engineering"]]
