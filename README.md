# DocPilot

**Ask questions about your documents and get answers that cite their sources, and refuse when the answer isn't there.**

DocPilot is a retrieval-augmented generation (RAG) service built with FastAPI, PostgreSQL + pgvector and any OpenAI-compatible LLM. It ships with an evaluation harness so retrieval and answer quality are measured, not guessed.

![CI](https://github.com/Gayathri2708/docpilot-rag/actions/workflows/ci.yml/badge.svg)

## Architecture

```mermaid
flowchart LR
    U[Web UI / API client] -->|upload| I[Ingestion]
    I --> X[Text extraction<br/>pypdf]
    X --> C[Sentence-aware chunking<br/>with overlap]
    C --> E[Local embeddings<br/>bge-small, fastembed]
    E --> DB[(Postgres + pgvector<br/>HNSW index)]

    U -->|question| R[Retrieval<br/>top-k cosine search]
    DB --> R
    R --> G{Relevance gate}
    G -->|below threshold| N[Refuse<br/>no LLM call]
    G -->|relevant| L[LLM with numbered sources<br/>streamed via SSE]
    L --> A[Answer + citations]

    EV[Eval harness] -.->|golden set| R
    EV -.-> L
```

## Features

- **Ingestion:** PDF, TXT and Markdown; duplicate uploads detected by SHA-256.
- **Chunking:** sentence-aware packing with overlap; chunks never cross pages, so every citation points to one page.
- **Embeddings:** local `BAAI/bge-small-en-v1.5` via fastembed: free, CPU-only, no PyTorch.
- **Vector search:** pgvector with an HNSW index. A `tsvector` column and GIN index are already in place for hybrid search.
- **Grounded answers:** numbered sources in the prompt, mandatory `[n]` citations, exact refusal sentence when the answer isn't in the sources.
- **Relevance gate:** if the best chunk scores below `MIN_RELEVANCE`, DocPilot refuses without calling the LLM. This cuts cost and removes a whole class of hallucinations.
- **Prompt-injection guard:** retrieved text is labelled untrusted data in the system prompt.
- **Streaming:** Server-Sent Events (`sources` → `token`… → `done` / `error`).
- **Observability:** per-request timings for retrieval and generation.
- **Provider-agnostic:** Gemini, OpenAI, Groq or a local Ollama model, switched by configuration only.
- **Evaluation harness:** retrieval hit@k and MRR, answer accuracy, refusal accuracy, false-refusal rate, citation rate and latency p50/p95.
- **Tests and CI:** unit and API tests run without a database or API key; GitHub Actions runs ruff and pytest on every push.

## Quickstart

Requirements: Python 3.11+, Docker.

```bash
# 1. Start Postgres with pgvector
docker compose up -d

# 2. Install and configure
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env        # then add LLM_API_KEY (a free Gemini key works)

# 3. Run
uvicorn app.main:app --reload
```

Open http://localhost:8000 for the UI, or http://localhost:8000/docs for the interactive API docs.
The first upload downloads the embedding model (~130 MB) once.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/documents` | Upload and index a file (multipart `file`) |
| `GET` | `/documents` | List indexed documents |
| `DELETE` | `/documents/{id}` | Remove a document and its chunks |
| `POST` | `/search` | Retrieval only: `{"query", "top_k"}` |
| `POST` | `/ask` | Answer with sources and timings: `{"question", "top_k"}` |
| `POST` | `/ask/stream` | Same, streamed as Server-Sent Events |
| `GET` | `/health` | Database and LLM configuration status |

## Evaluation

`evals/sample_docs/` holds five documents from one fictional company, Northwind Labs: an employee handbook, an engineering onboarding guide and a product FAQ (Markdown), and a travel & expense policy and an information security policy (PDF, 4 pages each). They deliberately overlap in topic but not in facts (paid leave vs. leave encashment, domestic vs. international hotel limits, internal P1 incidents vs. customer Priority 1 tickets), so retrieval has to pick the right document, not just the right topic.

`evals/golden.jsonl` holds 60 questions: 48 answerable, each with the exact evidence sentence and expected facts, and 12 that no document answers, to test refusal. They mix exact-term questions (policy codes such as `FIN-F12`, product names, numbers), paraphrased questions, multi-fact questions and near-miss unanswerable ones. A test checks that every evidence string survives extraction and chunking and appears in exactly one document.

```bash
# with the API running, from the repository root
python evals/run_eval.py --upload evals/sample_docs/*.md evals/sample_docs/*.pdf --label baseline
# on a rate-limited free LLM tier (e.g. 5 requests/minute), pace the run:
python evals/run_eval.py --delay 13
```

Each run prints a per-question PASS/FAIL list and saves a JSON report to `evals/results/`.

### Results

60 cases (48 answerable, 12 unanswerable), dense retrieval only, `top_k=5`, `MIN_RELEVANCE=0.55`, LLM `openai/gpt-oss-120b` on Groq, run on 13 Oct 2026.

| Run | hit@k | MRR | Answer acc. | Refusal acc. | False refusals | Citation rate | p50 / p95 latency |
|---|---|---|---|---|---|---|---|
| baseline (k=5) | 1.00 | 0.886 | 1.00 (48/48) | 1.00 (12/12) | 0.00 | 1.00 | 7.7 s / 9.7 s |

Notes:
- **Retrieval is the weak spot, not generation.** Every evidence chunk is in the top 5, but MRR 0.886 means the right chunk is often ranked 2nd to 5th, mostly on exact-term and cross-document questions (`fin-encashment` at rank 4, `fin-advance` at rank 5). This is what hybrid search is meant to fix.
- **Run-to-run variance:** an earlier run with the same settings scored 47/48 on answers. On `fin-intl-hotel` the model gave the USD 250 high-cost-city cap instead of the standard USD 180. Treat a single-question difference as noise.
- **Model portability:** switching from Gemini to gpt-oss on Groq needed only `.env` changes, but it exposed one bug: gpt-oss cites as `【1】`, which the citation parser didn't recognise (citation rate showed 0.27). The parser and UI now accept both bracket styles, with a test.
- Latency is dominated by the LLM call; the near-zero-latency case (7 ms) is a question refused by the relevance gate without calling the LLM.

### Experiments to run next

1. **Relevance threshold:** sweep `MIN_RELEVANCE` (0.45 → 0.70) and pick the value that keeps refusal accuracy high without raising false refusals.
2. **Chunk size:** compare `CHUNK_MAX_CHARS` 500 / 1000 / 1500 at `--top-k 3`.
3. **Hybrid search:** add BM25 over the existing `tsvector` column and measure whether exact-term questions (policy codes, product names) move to rank 1.

## Design decisions

- **pgvector over a dedicated vector database.** One datastore for documents, chunks, vectors and (soon) full-text search keeps transactions simple: a document and all its chunks are written atomically, and deletes cascade.
- **Local embeddings.** No per-token cost for indexing, no data leaves the machine at ingestion, and re-indexing is free while experimenting with chunking.
- **Refusal before generation.** A cheap similarity threshold decides whether to call the LLM at all, so unanswerable questions cost nothing and can't be hallucinated.
- **Filename as a contextual header.** Each chunk is embedded with its document name prepended, so short chunks keep their context.
- **Pages as hard chunk boundaries.** Slightly smaller chunks in exchange for citations that always point to a single page.

## Roadmap

- [ ] Next.js frontend
- [ ] Hybrid search (BM25 via `tsvector` + vector, reciprocal rank fusion) and a reranker
- [ ] LLM-as-judge faithfulness scoring in the eval harness
- [ ] Multi-tenancy: organizations, API keys, Postgres row-level security
- [ ] Async ingestion workers for large files
- [ ] Tracing with Langfuse / OpenTelemetry; semantic caching
- [ ] Deployment

## Project structure

```
backend/app/        FastAPI service: config, db, ingest, embeddings, retrieval, llm, main, static UI
backend/tests/      unit and API tests (no DB or API key needed)
evals/              golden set, sample document, eval harness and its tests
docker-compose.yml  Postgres 16 + pgvector
```

Note: the embedding dimension (384) is fixed in `schema.sql`. Changing `EMBEDDING_MODEL` to a model with a different dimension needs a matching schema change and a re-index.
