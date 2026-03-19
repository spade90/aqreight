# AI Policy & Product Helper

A local-first RAG assistant for answering company policy and product questions with citations.
Built with **FastAPI** (backend), **Next.js** (frontend), and **Qdrant** (vector DB).

---

## Quick Start (Docker — recommended)

```bash
# 1. Copy env (defaults to stub LLM — fully offline, no API key needed)
cp .env.example .env
# To use a real LLM for your demo: set LLM_PROVIDER=openrouter in .env

# 2. Boot everything
docker compose up --build

# 3. Ingest sample docs (or use the Admin tab in the UI)
curl -X POST http://localhost:8000/api/ingest

# 4. Ask a question
curl -X POST http://localhost:8000/api/ask \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is the shipping SLA to East Malaysia for bulky items?"}'
```

| Service  | URL                           |
|----------|-------------------------------|
| Frontend | http://localhost:3000         |
| Backend  | http://localhost:8000/docs    |
| Qdrant   | http://localhost:6333         |

---

## Quick Start (No Docker)

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
VECTOR_STORE=memory LLM_PROVIDER=stub \
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir .
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

---

## Environment Variables

| Variable              | Default                     | Description                              |
|-----------------------|-----------------------------|------------------------------------------|
| `LLM_PROVIDER`        | `stub`                      | `stub` (offline) \| `openrouter`         |
| `OPENROUTER_API_KEY`  | —                           | Required when `LLM_PROVIDER=openrouter`  |
| `LLM_MODEL`           | `openai/gpt-4o-mini`        | Any model available on OpenRouter        |
| `VECTOR_STORE`        | `qdrant`                    | `qdrant` \| `memory`                     |
| `QDRANT_HOST`         | `http://qdrant:6333`        | Qdrant service URL                       |
| `CHUNK_SIZE`          | `700`                       | Words per chunk                          |
| `CHUNK_OVERLAP`       | `80`                        | Overlap between adjacent chunks          |
| `MMR_LAMBDA`          | `0.72`                      | MMR relevance-diversity trade-off (0–1)  |
| `MASK_SENSITIVE_OUTPUT` | `true`                    | Redact emails, ICs, phones, addresses    |

---

## Running Tests

```bash
# Inside Docker (recommended — uses in-memory store automatically)
docker compose run --rm backend pytest -q

# Locally
cd backend
VECTOR_STORE=memory pytest -q
```

**Expected output:**
```
....                        [100%]
4 passed in X.XXs
```

## Smoke Eval

```bash
# Requires the stack to already be running (docker compose up)
python backend/app/eval_smoke.py --base-url http://localhost:8000
```

---

## Architecture

```
Browser
  │
  ▼
┌─────────────────────────────────────┐
│  Next.js Frontend (port 3000)       │
│  ┌──────────────┐  ┌─────────────┐  │
│  │  AdminPanel  │  │    Chat     │  │
│  │  (ingest +   │  │  (ask +     │  │
│  │   metrics)   │  │  citations) │  │
│  └──────┬───────┘  └──────┬──────┘  │
└─────────┼─────────────────┼─────────┘
          │  HTTP/REST       │
          ▼                  ▼
┌─────────────────────────────────────┐
│  FastAPI Backend (port 8000)        │
│                                     │
│  POST /api/ingest                   │
│    └─ load_documents()              │
│       chunk_text()                  │
│       embed + upsert to store       │
│                                     │
│  POST /api/ask                      │
│    └─ embed query                   │
│       vector search (k*4 candidates)│
│       hybrid rescore                │
│       (dense + lexical + phrase     │
│        + title + intent boost)      │
│       MMR diversity rerank          │
│       LLM.generate(query, ctx)      │
│       PDPA masking on output        │
│       return answer + citations     │
│                                     │
│  GET  /api/metrics                  │
│  GET  /api/health                   │
└────────────────┬────────────────────┘
                 │
          ┌──────┴──────┐
          │             │
          ▼             ▼
   ┌──────────┐   ┌───────────────┐
   │  Qdrant  │   │  OpenRouter   │
   │  vector  │   │  (GPT-4o-mini │
   │   store  │   │   or other)   │
   │ port 6333│   │  or StubLLM   │
   └──────────┘   └───────────────┘
```

### Retrieval Pipeline

```
query
  │
  ├─ tokenize + normalize (stem, strip punctuation)
  │
  ├─ embed with LocalEmbedder (SHA-1 hash-based, 384-dim)
  │
  ├─ ANN search Qdrant → top k*4 candidates
  │
  ├─ Hybrid rescore:
  │     0.42 × dense cosine similarity
  │   + 0.30 × keyword overlap (unigrams)
  │   + 0.18 × phrase overlap (bigrams)
  │   + 0.10 × title/section token match
  │   + 0.00–0.22 intent boost (policy category hints)
  │
  ├─ Score floor filter (drop chunks < 42% of top score)
  │
  └─ MMR rerank (λ=0.72) → final k chunks
```

---

## Code Structure

```
ai-policy-helper-starter-pack/
├─ backend/
│  ├─ app/
│  │  ├─ main.py          FastAPI app + endpoints
│  │  ├─ settings.py      All config via env vars
│  │  ├─ rag.py           Embedder, vector stores, retrieval, LLMs, metrics
│  │  ├─ models.py        Pydantic request/response schemas
│  │  ├─ ingest.py        File loader + Markdown section splitter + chunker
│  │  ├─ eval_smoke.py    CLI smoke eval for acceptance questions
│  │  └─ tests/
│  │     ├─ conftest.py   pytest fixtures (sets VECTOR_STORE=memory, no Qdrant needed)
│  │     └─ test_api.py   health, ingest, acceptance questions, PDPA masking
│  ├─ requirements.txt
│  └─ Dockerfile
├─ frontend/
│  ├─ app/
│  │  ├─ page.tsx         Root layout (hero + workspace grid)
│  │  ├─ layout.tsx
│  │  └─ globals.css      All styles (CSS variables, components)
│  ├─ components/
│  │  ├─ Chat.tsx         Message thread, citation badges, chunk expansion
│  │  └─ AdminPanel.tsx   Ingest button, metrics grid, readiness indicator
│  ├─ lib/api.ts          Typed fetch wrappers for backend
│  ├─ package.json
│  └─ Dockerfile
├─ data/                  Sample policy Markdown docs
├─ docker-compose.yml
├─ Makefile
└─ .env.example
```

---

## Trade-offs & Design Decisions

### Embedder: local hash-based vs sentence-transformers
The `LocalEmbedder` uses SHA-1 hash bucketing — zero dependencies, instant startup,
fully offline. Trade-off: weaker semantic understanding compared to a real transformer.
The hybrid rescore (lexical + phrase overlap) compensates significantly for keyword-heavy
policy text where term matching matters more than paraphrase understanding.

**What I'd change for production:** swap in `sentence-transformers/all-MiniLM-L6-v2`
(still runs CPU-only, ~80 MB) for proper semantic embeddings.

### Chunking: fixed word-window vs semantic
Fixed 700-word chunks with 80-word overlap are simple and reproducible. For policy docs
with clearly structured sections the section-aware loader (`_md_sections`) already gives
natural boundaries before fixed chunking kicks in.

**Trade-off:** a sentence-boundary chunker or semantic splitter would keep sentences whole
and reduce mid-sentence cuts. The current 700-word window is large enough that most
relevant passages fit in one chunk.

### Hybrid retrieval scoring
Static weights (0.42 dense / 0.30 lexical / 0.18 phrase / 0.10 title) were hand-tuned
against the acceptance test cases. For a larger corpus you'd want to learn these via a
cross-encoder reranker trained on click/feedback data.

### Qdrant vs in-memory
Qdrant persists across restarts and scales to millions of vectors. The in-memory fallback
means tests and offline development never need a running Qdrant instance.

### PDPA masking
Applied to both chunk text returned to the frontend **and** to LLM answer text.
Uses regex patterns for Malaysian IC numbers, phone numbers, emails, and street addresses.
Limitation: regex can miss novel formats; a proper NER model would be more robust.

---

## What I'd Ship Next

1. **Real embeddings** — `all-MiniLM-L6-v2` via `sentence-transformers` for semantic recall
2. **Cross-encoder reranker** — fine-tune a small BERT model on policy Q&A pairs
3. **Streaming responses** — Server-Sent Events for token-by-token LLM output
4. **Feedback loop** — thumbs up/down stored to SQLite → used to weight retrieval
5. **File upload endpoint** — drag-and-drop PDF/DOCX ingestion in the Admin panel
6. **Auth** — simple API key or OAuth before exposing to production users
7. **Caching** — LRU cache on repeated identical queries to cut LLM costs
8. **Guardrails** — prompt injection detection, out-of-scope query deflection
9. **Observability** — structured JSON logs + OpenTelemetry traces to Grafana
10. **Eval harness** — expand `eval_smoke.py` with RAGAS-style faithfulness + relevancy metrics
