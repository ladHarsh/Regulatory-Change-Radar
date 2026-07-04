# Regulatory Change Radar 📡

A production-grade, multi-stage RAG (Retrieval-Augmented Generation) compliance tracking and auditing engine. It automatically ingests, hashes, versions, and indexes regulatory documents (RBI, SEBI, IRDAI) to enable semantic clause diffing, automated conflict audits of internal policy files, and high-performance verification.

---

## 🚀 Key Features

1. **Modular Multi-Stage RAG Pipeline**: Uses a structured 6-stage flow (Query Analysis → Hybrid Retrieval → Confidence Gate → Reasoning Agent → Synthesis Agent → Verification Agent) rather than a single monolithic LLM call.
2. **Auto-Ingestion & Hash-Based Versioning**: Scrapes regulatory pages, parses raw text, and verifies updates using MD5 hash comparison to detect true revisions.
3. **High-Performance Hybrid Retrieval**: Executes dense vector search (`BAAI/bge-small-en-v1.5`) and sparse keyword retrieval (BM25) concurrently using a `ThreadPoolExecutor` and `asyncio.gather`. Fuses results via Reciprocal Rank Fusion (RRF) and reranks using a cross-encoder (`ms-marco-MiniLM-L-6-v2`).
4. **Optimized Multi-Tier Verification**: Minimizes latency via a 3-tier routing framework:
   * **Tier 1 (Programmatic)**: Uses Jaccard similarity and token intersection for fast factual checks (~0ms).
   * **Tier 2 (Lite LLM)**: Utilizes `llama-3.1-8b-instant` with capped evidence to quickly verify factual consistency (~270ms).
   * **Tier 3 (Full LLM)**: Employs a full adversarial verification model with extensive evidence for complex eligibility/scenario questions.
5. **Jaccard-Based Semantic Query Cache**: Returns instant cached answers (~190ms HTTP) for repetitive queries. Cache automatically invalidates on new document ingestion.
6. **Mobile-First UX Redesign**:
   * **Chat Screen (`/query`)**: Formatted with a clean flex layout utilizing `100dvh` (dynamic viewport height) and `visualViewport` listener for keyboard-pinning safety. Bottom navigation is hidden to maximize vertical space, replaced by a contextual mobile header with a back button and action menu (with a deletion confirmation modal).
   * **Evaluation Dashboard (`/evaluation`)**: Features a compact, responsive 2-column grid layout on mobile (P95 Latency spans full width). Tap triggers open dynamic, touch-friendly `BottomSheet` drawers showing SVG trend sparklines, historical runs, and filtered query breakdowns.

---

## ⚡ Technical Performance Achievements

Through a series of optimizations (tiered verification, model resizing, parallelized retrieval, evidence capping, and caching), the steady-state performance of the pipeline was substantially enhanced:

| Stage | Baseline (avg) | Post-Optimization (Warm Path) | Reduction |
|---|---|---|---|
| Retrieval | 3,795 ms | **989 ms** | **-74.0%** |
| Reasoning | 3,683 ms | **0 ms** (Factual Bypass) | **-100%** |
| Synthesis | 12,762 ms | **766 ms** (Evidence capped) | **-94.0%** |
| Verification | 41,072 ms | **279 ms** (Tier 2, 8B model) | **-99.3%** |
| **Total Query** | **61,314 ms** | **~2,036 ms** (Factual queries) | **-96.6%** |
| Cache Hit | — | **~191 ms** (HTTP Round-trip) | — |
| 25-Case Eval | ~30 min | **~4 min** (Concurrently batch of 3) | **-86.6%** |

---

## 🧹 Codebase Cleanup & Architecture Audit

Prior to the `v3` release, a complete architecture audit was performed resulting in a significantly leaner footprint:
- **Dead Files Removed**: 17+ debug and legacy log files deleted (e.g. `qual_chunk.txt`, `debug_run*.txt`, obsolete SQLite shards).
- **Dependencies Optimized**: Removed unused `difflib2` in Python backend and `clsx` from the React frontend, relying purely on built-in native modules and core Tailwind.
- **Dead Code Eliminated**: Scrubbed unused imports (`uuid`, `cosine_similarity`) across the pipeline via static analysis (`vulture` and `depcheck`) to tighten execution paths and maintain 100% active endpoints.

---

## 🛠️ Project Structure

```
├── backend/
│   ├── app/
│   │   ├── api/             # FastAPI routers (documents, changes, query, policy, evaluation)
│   │   ├── db/              # SQLAlchemy schemas, database session, and SQLite models
│   │   ├── diffing/         # Core semantic clause diffing algorithm
│   │   ├── evaluation/      # Parallelized evaluation runner & test suite
│   │   ├── ingestion/       # Scrapers, text parsers, chunking logic
│   │   ├── llm/             # LLM prompt templates and Groq client initialization
│   │   ├── rag/             # Multi-stage RAG components (Query Analyzer, agents, cache)
│   │   └── retrieval/       # BM25 indexer, vector stores, hybrid search, cross-encoder
│   ├── data/                # SQLite metadata DB and ChromaDB vector files
│   ├── venv/                # Python virtual environment
│   └── requirements.txt     # Python backend dependencies
└── frontend/
    ├── src/
    │   ├── api/             # Axios API client, queryRagStream SSE consumer
    │   ├── components/      # BottomSheet, Layout templates, DiffView toggle
    │   ├── pages/           # Pages (Dashboard, Timeline, PolicyCheck, Query, Evaluation)
    │   ├── store/           # Zustand state management (chat history persistence, filters)
    │   └── index.css        # Responsive layouts and CSS design system rules
    └── package.json         # Frontend modules and build configurations
```

---

## 💻 Installation & Setup

### Prerequisites
* Python 3.10+ (tested on Python 3.13)
* Node.js 18+ (tested on Node.js 20)
* Free Groq API Key (configure in `.env`)

### 1. Backend Setup
1. Navigate to the backend directory and activate the virtual environment:
   ```bash
   cd backend
   python -m venv venv
   # On Windows:
   .\venv\Scripts\Activate.ps1
   # On macOS/Linux:
   source venv/bin/activate
   ```
2. Install Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables. Create a `.env` file from the template:
   ```bash
   cp .env.example .env
   ```
   Provide your `GROQ_API_KEY` inside `.env`.
4. Start the backend server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   API docs will render at `http://127.0.0.1:8000/docs`.

### 2. Frontend Setup
1. Navigate to the frontend directory:
   ```bash
   cd ../frontend
   ```
2. Install packages:
   ```bash
   npm install --legacy-peer-deps
   ```
3. Launch the development server:
   ```bash
   npm run dev
   ```
   The application will be accessible at `http://localhost:5173`.

---

## 📊 Running Evaluations

The application includes a parallelized evaluation runner that benchmarks retrieval accuracy (Recall@5), answer accuracy (LLM-as-judge), hallucination rate, and latency.

To trigger evaluation, you can use the Frontend Evaluation Dashboard page or run it via command line:
```bash
cd backend
.\venv\Scripts\python -c "import asyncio; from app.db.session import SessionLocal; from app.evaluation.runner import run_evaluation_suite; asyncio.run(run_evaluation_suite(SessionLocal()))"
```
This runs the 25 test cases concurrently in throttled batches to avoid API rate limits, completing in under 5 minutes.

---

## 📱 Mobile-First UI/UX & Responsive Views

* **Query/Ask Radar Screen**: Eliminates browser chrome bugs by sizing the wrapper using `100dvh`. Bottom nav is hidden during active chats to yield space to the keyboard and content, and a clean contextual header with a back button is provided. Clear Chat requires clicking through a visual modal confirm card.
* **Evaluation Dashboard**: Formatted as a compact grid on screens `< 640px` with sparklines hidden on cards. Metrics values are highlighted. Clicking a card slides up a smooth, drag-to-dismiss `BottomSheet` displaying comprehensive history runs, filtered per-question results tables, and enlarged SVG trend charts.

---

## ⚠️ Known Limitations
* **Model Cold Start**: On the first request after a server boot, loading the embedding model (`bge-small-en-v1.5`) and cross-encoder reranker from local storage creates a one-time cold latency spike of ~16s. Warm paths run at ~2s.
* **Rate Limits on Free Tier APIs**: Running concurrent batches during evaluations uses exponential backoff to handle HTTP 429 warnings from free Groq endpoints.
