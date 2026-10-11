"""DocPilot evaluation harness.

Runs every question in a golden set against a running DocPilot API and reports:
  - Retrieval hit@k and MRR      : did the chunk containing the evidence come back, and how high?
  - Answer accuracy              : answerable questions whose answer contains the expected facts
  - Refusal accuracy             : unanswerable questions correctly refused (no hallucination)
  - False refusals               : answerable questions the system wrongly refused
  - Citation rate                : answered questions that cite at least one source
  - Latency p50 / p95

Usage (API running on localhost:8000):
    python evals/run_eval.py --upload evals/sample_docs/northwind_handbook.md
    python evals/run_eval.py --top-k 3 --label "k=3"

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
    return " ".join(text.replace("’", "'").lower().split())


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


@dataclass
class Report:
    label: str
    top_k: int
    cases: list[CaseResult] = field(default_factory=list)

    def summary(self) -> dict:
        ans = [c for c in self.cases if c.answerable]
        unans = [c for c in self.cases if not c.answerable]
        answered = [c for c in self.cases if not c.refused]
        latencies = [c.latency_ms for c in self.cases]

        def ratio(n: int, d: int) -> float:
            return round(n / d, 3) if d else 0.0

        return {
            "cases": len(self.cases),
            "retrieval_hit_at_k": ratio(sum(c.retrieval_rank is not None for c in ans), len(ans)),
            "retrieval_mrr": round(
                statistics.fmean([1 / c.retrieval_rank if c.retrieval_rank else 0 for c in ans]), 3
            ) if ans else 0.0,
            "answer_accuracy": ratio(sum(c.correct for c in ans), len(ans)),
            "refusal_accuracy": ratio(sum(c.refused for c in unans), len(unans)),
            "false_refusal_rate": ratio(sum(c.refused for c in ans), len(ans)),
            "citation_rate": ratio(sum(c.cited for c in answered), len(answered)),
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
        }


def load_golden(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(base_url: str, golden: list[dict], top_k: int, label: str) -> Report:
    report = Report(label=label, top_k=top_k)
    with httpx.Client(base_url=base_url, timeout=120) as client:
        for case in golden:
            hits = client.post("/search", json={"query": case["question"], "top_k": top_k}).raise_for_status().json()
            rank = evidence_rank(case["evidence"], [h["content"] for h in hits]) if case["evidence"] else None

            start = time.perf_counter()
            resp = client.post("/ask", json={"question": case["question"], "top_k": top_k}).raise_for_status().json()
            latency = round((time.perf_counter() - start) * 1000)

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
            ))
            status = "PASS" if correct else "FAIL"
            print(f"  {status}  {case['id']:<20} rank={rank}  {latency} ms")
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
    parser.add_argument("--label", default="baseline", help="name for this run, e.g. 'k=3' or 'hybrid-search'")
    parser.add_argument("--out-dir", type=Path, default=HERE / "results")
    args = parser.parse_args()

    if args.upload:
        upload(args.base_url, args.upload)

    golden = load_golden(args.golden)
    print(f"Running {len(golden)} cases (top_k={args.top_k}, label={args.label})")
    report = run(args.base_url, golden, args.top_k, args.label)
    summary = report.summary()

    print("\nResults")
    for key, value in summary.items():
        print(f"  {key:<22} {value}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{args.label.replace(' ', '_')}.json"
    out.write_text(json.dumps(
        {"label": report.label, "top_k": report.top_k, "summary": summary, "cases": [asdict(c) for c in report.cases]},
        indent=2, ensure_ascii=False,
    ))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
