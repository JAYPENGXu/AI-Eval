# AGENTS.md

This file gives coding agents project-level guidance for working in AIAssistant.

## Project Overview

AIAssistant is a phase-one RAG assistant, debugging workbench, and evaluation management system.

The current product goal is not to build a full Agent first. The project intentionally makes the RAG loop visible and measurable:

```text
document upload
-> chunking
-> indexing
-> query rewrite
-> vector search + BM25
-> hybrid fusion
-> rerank
-> context compression
-> final prompt
-> streaming answer
-> trace
-> evaluation
-> failure analysis
-> regression case
```

The next phase can add Agent orchestration, Function Calling, and tool execution on top of this RAG and evaluation foundation.

## Important Paths

- `backend/`: Django + Django REST Framework backend.
- `backend/rag/`: RAG domain models, API views, retrieval logic, chunking, evaluation, and management commands.
- `backend/vector_store/`: local vector-related data that can be rebuilt from database chunks.
- `frontend/`: Vue 3 + Vite frontend.
- `frontend/src/`: main Vue source code.
- `README.md`: architecture, setup, current system capabilities.
- `一期功能说明.md`: Chinese beginner-friendly phase-one feature document.

## Repository Conventions

- Keep backend changes scoped to `backend/rag/` unless settings, URLs, or migrations require otherwise.
- Keep frontend changes scoped to `frontend/src/` and existing Vue/Vite patterns.
- Preserve Chinese user-facing copy unless the task explicitly asks to rewrite it.
- Prefer small, direct changes over broad refactors.
- Do not commit generated caches, local databases, virtual environments, dependency folders, or vector-store rebuild artifacts unless explicitly requested.
- SQLite is the source of truth for business data and evaluation data. Milvus/vector data should be treated as rebuildable index data.

## Backend Setup

From `backend/`:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8010
```

The backend reads configuration from `backend/.env`. Important variables include:

```text
API_KEY
API_BASE
CHAT_MODEL
EMBEDDING_MODEL
EMBEDDING_DIMENSIONS
```

Optional model/provider variables can be used for LLM rewrite, LLM compression, reranking, or provider-specific APIs.

## Frontend Setup

From `frontend/`:

```bash
npm install
npm run dev -- --host 0.0.0.0 --port 5174
```

The frontend normally runs at:

```text
http://localhost:5174
```

The Django backend normally runs at:

```text
http://127.0.0.1:8010
```

## Verification Commands

Use the narrowest useful verification for the change.

Backend:

```bash
cd backend
source venv/bin/activate
python -m compileall rag
python manage.py check
python manage.py makemigrations --check --dry-run
```

Frontend:

```bash
cd frontend
npm run build
```

Evaluation command:

```bash
cd backend
source venv/bin/activate
python manage.py eval_ragas --suite regression
```

If dependencies are not installed in the current environment, say so clearly instead of pretending checks passed.

## RAG Pipeline

The main RAG flow is:

```text
original query
-> query rewrite
-> vector search
-> BM25 search
-> hybrid fusion with RRF
-> rerank
-> context compression
-> final prompt
-> streaming LLM answer
-> RagTrace persistence
```

Query rewrite strategies:

- `none`: use the original question.
- `rule`: default lightweight keyword rewrite.
- `llm`: call an LLM to generate a retrieval-oriented query.

Chunking strategies:

- token chunking
- sentence chunking
- sentence-window chunking
- semantic chunking
- markdown chunking

Compression strategies may include no compression, rule-based sentence filtering, structure-aware compression, and LLM compression.

## Workbench UI

The frontend has three major columns:

- Left: knowledge base, documents, chunking, indexing, reset.
- Middle: debug workbench.
- Right: RAG chat with SSE streaming.

The middle workbench is organized into tabs:

- `Debug`: chunking lab, RAG retrieval debug, parameter tuning.
- `Evaluation`: run evaluations, inspect reports, compare runs, view Failure Analysis.
- `Datasets`: maintain benchmark, smoke, regression, and release cases.
- `History`: inspect traces, compare traces, convert trace failures to regression cases.

When adding new RAG variables, prefer making them visible in the workbench so users can observe how each layer changes.

## Evaluation And Dataset Management

The system stores evaluation cases in the database instead of relying only on JSON examples.

`RagBenchmarkCase` should capture:

- question
- reference answer
- expected terms
- target chunk ids
- suite: `smoke`, `benchmark`, `regression`, `release`
- tags
- difficulty
- source: expert, trace, eval failure, user feedback, default JSON
- notes
- enabled flag

`RagEvalRun` represents one evaluation run and its parameter snapshot.

`RagEvalCaseResult` represents one case result and should preserve:

- RAGAS scores
- retrieval hit diagnostics
- Hit Rate
- Recall@K
- MRR
- failure reasons
- stage-level details for vector, BM25, hybrid, rerank, compression, and final answer.

Failure categories include:

- `rewrite_failed`
- `vector_miss`
- `bm25_miss`
- `hybrid_drop`
- `rerank_drop`
- `compression_lost`
- `llm_answer_wrong`
- `no_reference`
- `target_chunk_stale`

## Regression Loop

The project is designed to improve through a closed loop:

```text
real question
-> trace
-> failure analysis
-> regression case
-> evaluation run
-> parameter/model/prompt improvement
-> rerun regression
```

The frontend supports converting both trace failures and evaluation failures into regression cases. Keep this loop working when changing APIs or UI state.

## API Notes

Common API areas:

- auth: register, login, current user
- knowledge bases
- documents: upload, preview chunks, index, list chunks
- chat sessions and messages
- SSE chat endpoint
- RAG traces: list, detail, compare
- benchmark cases: CRUD, import defaults, create from trace, create from eval failure
- evaluation runs: list, detail, run, poll status, compare
- reset workspace

When changing a response shape, update both backend serializer/view code and frontend API/state usage in the same change.

## Editing Notes

- Add Django migrations when model fields change.
- Update admin registration/list displays when a model becomes operationally important.
- Keep evaluation fallback behavior: if no enabled database benchmark cases exist, the system may fall back to default JSON examples.
- Keep SSE event format stable unless the frontend is updated at the same time.
- Keep user-facing debug labels clear and concrete. This project is a learning system, so explainability matters.
