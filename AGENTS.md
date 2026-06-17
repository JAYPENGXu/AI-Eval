# AGENTS.md

This file gives coding agents project-level guidance for working in AIAssistant.

## Project Overview

AIAssistant is a RAGOps learning and engineering project. It has two connected phases:

- Phase 1: a RAG knowledge-base Q&A, visual debugging, evaluation, and regression management system.
- Phase 2: a LangGraph-based RAGOps Agent workflow with Human-in-the-loop actions.

The product goal is not to be a generic chatbot. It is a system for making RAG behavior visible, measurable, and improvable.

Current end-to-end loop:

```text
document upload
-> chunking
-> indexing
-> query intent routing
-> session summary memory + recent turns
-> conversational query rewrite
-> retrieval query rewrite
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
-> Agent diagnosis / HITL action
```

## Important Paths

- `backend/`: Django + Django REST Framework backend.
- `backend/assistant_backend/settings.py`: project settings and environment variables.
- `backend/rag/`: RAG domain models, API views, retrieval logic, evaluation, and management commands.
- `backend/rag/services.py`: main RAG question-answering pipeline.
- `backend/rag/query_router.py`: lightweight internal knowledge vs web-required route decision.
- `backend/rag/query_rewrite.py`: retrieval query rewrite logic.
- `backend/rag/agent/`: LangGraph RAGOps Agent workflow.
- `backend/rag/experiments.py`: parameter experiment planning and execution helpers.
- `backend/rag/case_factory.py`: creates regression cases from Trace, Eval Failure, and user feedback.
- `backend/vector_store/`: local vector-related data that can be rebuilt.
- `backend/agent_state/`: LangGraph SQLite checkpoint data; never commit.
- `frontend/`: Vue 3 + Vite + Element Plus frontend.
- `frontend/src/App.vue`: main workbench shell and top-level state.
- `frontend/src/components/`: frontend panels and reusable components.
- `frontend/src/api/`: frontend API modules.
- `README.md`: project overview and setup.
- `一期功能说明.md`: phase-one RAG feature guide.
- `二期功能说明.md`: phase-two Agent workflow guide.

## Repository Conventions

- Keep backend changes scoped to `backend/rag/` unless settings, URLs, or migrations require otherwise.
- Keep frontend changes scoped to `frontend/src/` and existing Vue/Vite/Element Plus patterns.
- Preserve Chinese user-facing copy unless the task explicitly asks to rewrite it.
- Prefer small, direct changes over broad refactors.
- Do not commit generated caches, local databases, virtual environments, frontend build output, uploaded media, vector-store rebuild artifacts, or LangGraph checkpoint files.
- SQLite is the source of truth for business data and evaluation data.
- Milvus/vector data is a rebuildable index.
- LangGraph checkpoint data stores Agent execution state, not business facts.

## Backend Setup

From `backend/`:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8010
```

The backend reads configuration from `backend/.env`.

Important variables include:

```text
API_KEY
API_BASE
CHAT_MODEL
EMBEDDING_MODEL
EMBEDDING_DIMENSIONS
DASHSCOPE_API_KEY
DEEPSEEK_API_KEY
MILVUS_URI
MILVUS_COLLECTION
CONVERSATION_CONTEXT_TURNS
SESSION_SUMMARY_ENABLED
SESSION_SUMMARY_TRIGGER_MESSAGES
SESSION_SUMMARY_MAX_CHARS
LANGGRAPH_CHECKPOINT_DB
```

## Frontend Setup

From `frontend/`:

```bash
npm install
npm run dev -- --host 0.0.0.0 --port 5174
```

This project uses Vite 7, so use Node 20.19+.

Known local Node path used in this workspace:

```bash
export PATH=/home/peng/AIFriends/.local/node-v20.19.0-linux-x64/bin:$PATH
```

Frontend URL:

```text
http://localhost:5174
```

Backend URL:

```text
http://127.0.0.1:8010
```

## Verification Commands

Use the narrowest useful verification for the change.

Backend:

```bash
cd backend
source venv/bin/activate
python -m compileall rag assistant_backend
python manage.py check
python manage.py makemigrations --check --dry-run
```

Frontend:

```bash
cd frontend
export PATH=/home/peng/AIFriends/.local/node-v20.19.0-linux-x64/bin:$PATH
npm run build
```

Evaluation command:

```bash
cd backend
source venv/bin/activate
python manage.py eval_ragas --suite regression
```

If dependencies are missing, say so clearly instead of pretending checks passed.

## RAG Pipeline

The current RAG flow is:

```text
original question
-> query router: internal_knowledge / web_required
-> ChatSessionSummary + recent ChatSession context
-> conversational query rewrite
-> retrieval query rewrite
-> vector search
-> BM25 search
-> hybrid fusion with RRF
-> rerank
-> context compression
-> final prompt
-> streaming LLM answer
-> RagTrace persistence
```

Conversational rewrite uses recent session turns to resolve references such as:

- 他 / 她
- 这个 / 那个
- 刚才 / 上一个
- 这位 / 此人

Do not confuse this with long-term memory. It is short-term session context for retrieval.


### Query Router And Memory

The RAG path intentionally supports only two route classes for now:

- `internal_knowledge`: continue into the internal RAG pipeline.
- `web_required`: reject with a clear message because Web Search is not connected yet.

Other broad intents should be rejected rather than forced through internal retrieval.

Session memory has three different meanings:

- Recent turns: short-term context for conversational rewrite.
- `ChatSessionSummary`: medium-term session summary generated by a background thread after `SESSION_SUMMARY_TRIGGER_MESSAGES` new messages.
- Knowledge base: long-term document memory through `Document`, `Chunk`, and Milvus.

Do not block SSE responses while updating `ChatSessionSummary`. The summary job should be best-effort and record failure in `ChatSessionSummary.status/error_message`.

Trace settings should keep memory observability fields such as `session_summary_used`, `session_summary_chars`, and `session_summary_message_count`.

Retrieval query rewrite strategies:

- `none`: use the original standalone question.
- `rule`: default lightweight keyword rewrite.
- `llm`: call an LLM to generate a retrieval-oriented query.

Chunking strategies:

- token chunking
- sentence chunking
- sentence-window chunking
- semantic chunking
- markdown chunking

Compression strategies may include:

- no compression
- sentence filtering
- structure-aware compression
- LLM compression

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
- `Agent`: end-to-end RAG repair workflow.
- `Costs`: model usage, token, cost, slow requests, failed requests.

When adding new RAG variables, make them observable in the workbench whenever reasonable.

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
- stage-level details for vector, BM25, hybrid, rerank, compression, and final answer

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

Regression cases can come from:

- Trace failures.
- Evaluation failures.
- User negative feedback.

Keep this loop working when changing APIs or UI state.

## RAGOps Agent

The Agent is not a generic assistant. It is a RAGOps repair workflow.

Current frontend entry:

```text
端到端 RAG 修复工作流
```

Expected workflow:

```text
failed Trace or Baseline Eval Run
-> collect evidence
-> diagnose failure stage
-> propose fixes
-> create HITL Action Card for write operations
-> user confirms
-> create regression case or run experiment
-> audit result
```

LangGraph files:

- `backend/rag/agent/graph.py`
- `backend/rag/agent/tools.py`
- `backend/rag/agent/checkpointing.py`
- `backend/rag/agent/services.py`

Graph state rules:

- Store IDs and compact summaries only.
- Do not put large documents, large chunks, or full traces into LangGraph state.
- Fetch ORM objects inside nodes/tools when needed.
- Business facts belong in Django models.
- Agent execution state belongs in the checkpointer.

Current graph nodes include:

- planner
- tool executor
- diagnostician
- proposal
- human decision
- responder

## HITL And Agent Actions

Agent write operations must go through Human-in-the-loop.

Use `RagAgentAction` for:

- creating Regression Case from Trace
- creating Regression Case from Eval Failure
- creating Regression Case from user feedback
- running parameter experiment plan

Statuses:

- `pending`
- `completed`
- `failed`
- `rejected`

Do not let the Agent silently perform write operations from a natural-language response.

## LangGraph Checkpointer

LangGraph checkpoint data is stored in an independent SQLite file:

```text
backend/agent_state/langgraph_checkpoints.sqlite3
```

Rules:

- Do not use Django `db.sqlite3` for checkpointer data.
- Do not commit `backend/agent_state/`.
- The frontend generates and stores the current Agent thread id.
- Backend passes thread id through `configurable.thread_id`.
- Thread id should bind to business context such as kb, trace, eval run, and compare run.
- Full interrupt/resume is not complete yet; do not claim it is.

## API Notes

Common API areas:

- auth: register, login, current user
- knowledge bases
- documents: upload, preview chunks, index, list chunks
- chat sessions and messages
- SSE chat endpoint
- RAG traces: list, detail, compare
- benchmark cases: CRUD, import defaults, create from trace, create from eval failure
- user feedback
- evaluation runs: list, detail, run, poll status, compare
- experiment plans
- model usage summary
- RAGOps Agent run
- Agent actions: list, confirm, reject
- reset workspace

When changing a response shape, update backend serializer/view code and frontend API/state usage in the same change.

## Editing Notes

- Add Django migrations when model fields change.
- Update admin registration/list displays when a model becomes operationally important.
- Keep evaluation fallback behavior: if no enabled database benchmark cases exist, the system may fall back to default JSON examples.
- Keep SSE event format stable unless the frontend is updated at the same time.
- Keep user-facing debug labels clear and concrete. This project is a learning system, so explainability matters.
- Prefer Element Plus components and the existing component structure for frontend UI.
- Do not reintroduce the old four-card Agent task UI unless explicitly requested; the current Agent product direction is a single end-to-end RAG repair workflow.
