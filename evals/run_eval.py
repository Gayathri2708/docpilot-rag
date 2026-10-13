"""DocPilot evaluation harness.

Runs every question in a golden set against a running DocPilot API and reports:
  - Retrieval hit@1, hit@k, MRR  : did the chunk containing the evidence come back, and how high?
  - Answer accuracy              : answerable questions whose answer contains the expected facts
  - Refusal accuracy             : unanswerable questions correctly refused (no hallucination)
  - False refusals               : answerable questions the system wrongly refused
  - Citation rate                : answered questions that cite at least one source
  - Latency p50 / p95, for retrieval alone and for the full /ask call

Usage (API running on localhost:8000):
    python evals/run_eval.py --upload evals/sample_docs/northwind_handbook.md
    python evals/run_eval.py --top-k 3 --label "k=3"
    python evals/run_eval.py --delay 13   # stay under a 5 requests/minute free-tier LLM quota
    python evals/run_eval.py --mode hybrid+rerank
    python evals/run_eval.py --mode hybrid --retrieval-only   # no LLM calls

Results are written to evals/results/<timestamp>.json so runs can be compared.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).parent

Keyword = str | list[str]  # a list means "any of these alternatives"


def normalize(text: str) -> str:
    return " ".join(text.replace("’", "'").replace("\u2011", "-").lower().split())


def keywords_match(answer: str, keywords: list[Keyword]) -> bool:
    """Every keyword group must appear; a group that is a list matches if any alternative appears."""
    text = normalize(answer)
    for group in keywords:
        options = [group] if isinstance(group, str) else group
        if not any(normalize(opt) in text for opt in options):
            return False
    return True


def is_refusal(answer: str) -> bool:
    text = normalize(answer)
    return "couldn't find" in text or "could not find" in text


def evidence_rank(evidence: str, chunks: list[str]) -> int | None:
    """1-based rank of the first retrieved chunk containing the evidence, or None."""
    target = normalize(evidence)
    for rank, chunk in enumerate(chunks, start=1):
        if target in normalize(chunk):
            return rank
    return None


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


@dataclass
class CaseResult:
    id: str
    question: str
    answerable: bool
    answer: str
    retrieval_rank: int | None
    correct: bool
    refused: bool
    cited: bool
    latency_ms: int
    retrieval_ms: int


@dataclass
class Report:
    label: str
    top_k: int
    mode: str = "vector"
    retrieval_only: bool = False
    cases: list[CaseResult] = field(default_factory=list)

    def summary(self) -> dict:
        ans = [c for c in self.cases if c.answerable]
        unans = [c for c in self.cases if not c.answerable]
        answered = [c for c in self.cases if not c.refused]
        latencies = [c.latency_ms for c in self.cases]
        retrieval_latencies = [c.retrieval_ms for c in self.cases]

        def ratio(n: int, d: int) -> float:
            return round(n / d, 3) if d else 0.0

        retrieval = {
            "cases": len(self.cases),
            "retrieval_hit_at_1": ratio(sum(c.retrieval_rank == 1 for c in ans), len(ans)),
            "retrieval_hit_at_k": ratio(sum(c.retrieval_rank is not None for c in ans), len(ans)),
            "retrieval_mrr": round(
                statistics.fmean([1 / c.retrieval_rank if c.retrieval_rank else 0 for c in ans]), 3
            ) if ans else 0.0,
            "retrieval_p50_ms": percentile(retrieval_latencies, 50),
            "retrieval_p95_ms": percentile(retrieval_latencies, 95),
        }
        if self.retrieval_only:
            return retrieval
        return {
            **retrieval,
            "answer_accuracy": ratio(sum(c.correct for c in ans), len(ans)),
            "refusal_accuracy": ratio(sum(c.refused for c in unans), len(unans)),
            "false_refusal_rate": ratio(sum(c.refused for c in ans), len(ans)),
            "citation_rate": ratio(sum(c.cited for c in answered), len(answered)),
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
        }


def load_golden(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# 429 = rate limited; 502 = the API reporting an LLM provider error (it maps the provider's 429 to 502).
RETRYABLE_STATUS = {429, 502}


# --mode values -> request options. rerank is always explicit so the server's RERANK default can't leak in.
MODES = {
    "vector": {"mode": "vector", "rerank": False},
    "hybrid": {"mode": "hybrid", "rerank": False},
    "hybrid+rerank": {"mode": "hybrid", "rerank": True},
}


def ask_with_retry(
    client: httpx.Client, question: str, top_k: int, options: dict | None = None, retries: int = 5
) -> tuple[dict, int]:
    """POST /ask, retrying rate-limit and provider errors with exponential backoff (15s, 30s, 60s, ...).
    Returns the response body and the latency of the successful attempt only, so backoff waits don't skew p95."""
    for attempt in range(retries + 1):
        start = time.perf_counter()
        resp = client.post("/ask", json={"question": question, "top_k": top_k, **(options or {})})
        latency = round((time.perf_counter() - start) * 1000)
        if resp.status_code not in RETRYABLE_STATUS or attempt == retries:
            return resp.raise_for_status().json(), latency
        wait = min(15 * 2**attempt, 240)
        print(f"    HTTP {resp.status_code}, retrying in {wait}s", flush=True)
        time.sleep(wait)
    raise AssertionError("unreachable")


def run(
    base_url: str,
    golden: list[dict],
    top_k: int,
    label: str,
    delay: float = 0,
    mode: str = "vector",
    retrieval_only: bool = False,
) -> Report:
    options = MODES[mode]
    report = Report(label=label, top_k=top_k, mode=mode, retrieval_only=retrieval_only)
    with httpx.Client(base_url=base_url, timeout=120) as client:
        for i, case in enumerate(golden):
            if i and delay and not retrieval_only:
                time.sleep(delay)
            start = time.perf_counter()
            hits = client.post(
                "/search", json={"query": case["question"], "top_k": top_k, **options}
            ).raise_for_status().json()
            retrieval_ms = round((time.perf_counter() - start) * 1000)
            rank = evidence_rank(case["evidence"], [h["content"] for h in hits]) if case["evidence"] else None

            if retrieval_only:
                report.cases.append(CaseResult(
                    id=case["id"], question=case["question"], answerable=case["answerable"], answer="",
                    retrieval_rank=rank, correct=False, refused=False, cited=False, latency_ms=0,
                    retrieval_ms=retrieval_ms,
                ))
                print(f"  {case['id']:<24} rank={rank}  {retrieval_ms} ms", flush=True)
                continue

            resp, latency = ask_with_retry(client, case["question"], top_k, options)

            refused = (not resp["answered"]) or is_refusal(resp["answer"])
            if case["answerable"]:
                correct = not refused and keywords_match(resp["answer"], case["answer_keywords"])
            else:
                correct = refused
            report.cases.append(CaseResult(
                id=case["id"],
                question=case["question"],
                answerable=case["answerable"],
                answer=resp["answer"],
                retrieval_rank=rank,
                correct=correct,
                refused=refused,
                cited=any(s["cited"] for s in resp["sources"]),
                latency_ms=latency,
                retrieval_ms=retrieval_ms,
            ))
            status = "PASS" if correct else "FAIL"
            print(f"  {status}  {case['id']:<20} rank={rank}  {latency} ms", flush=True)
    return report


def upload(base_url: str, paths: list[Path]) -> None:
    with httpx.Client(base_url=base_url, timeout=300) as client:
        for path in paths:
            with path.open("rb") as fh:
                data = client.post("/documents", files={"file": (path.name, fh)}).raise_for_status().json()
            note = ", already indexed" if data["duplicate"] else ""
            print(f"Uploaded {data['filename']} ({data['num_chunks']} chunks{note})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--golden", type=Path, default=HERE / "golden.jsonl")
    parser.add_argument("--upload", type=Path, nargs="*", default=[], help="documents to index before evaluating")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--delay", type=float, default=0, help="seconds between cases, for rate-limited LLM tiers")
    parser.add_argument("--mode", choices=MODES, default="vector", help="retrieval mode to evaluate")
    parser.add_argument("--retrieval-only", action="store_true", help="measure retrieval only; no LLM calls")
    parser.add_argument("--label", help="name for this run, e.g. 'k=3'; defaults to the mode")
    parser.add_argument("--out-dir", type=Path, default=HERE / "results")
    args = parser.parse_args()

    if args.upload:
        upload(args.base_url, args.upload)

    label = args.label or args.mode
    golden = load_golden(args.golden)
    print(f"Running {len(golden)} cases (top_k={args.top_k}, mode={args.mode}, label={label})")
    report = run(args.base_url, golden, args.top_k, label, args.delay, args.mode, args.retrieval_only)
    summary = report.summary()

    print("\nResults")
    for key, value in summary.items():
        print(f"  {key:<22} {value}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{label.replace(' ', '_').replace('+', '_')}.json"
    out.write_text(json.dumps(
        {
            "label": report.label,
            "mode": report.mode,
            "top_k": report.top_k,
            "summary": summary,
            "cases": [asdict(c) for c in report.cases],
        },
        indent=2, ensure_ascii=False,
    ))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
