# AIAssistant

AIAssistant 是一个面向 RAGOps 的知识库问答、调试、评测和 Agent 工作流系统。项目最初从 AIFriends 的对话能力中拆分出来，一期先把 RAG 问答链路做成可观察、可调参、可评测、可回归的工程闭环；二期在这个底座上引入 LangGraph Agent、Human-in-the-loop 和自动化诊断工作流。

当前项目不是一个普通“上传文档然后聊天”的 Demo，而是一个用于学习和演示 RAG 工程化演进的系统：

- 用户可以上传文档、选择切片方式、建立索引并基于知识库问答。
- 系统会先通过 Query Router 判断问题是否属于内部知识库，实时/联网类问题会被显式拦截。
- 长对话会异步生成 Session Summary，后续问题改写会结合摘要和最近几轮消息。
- 开发者可以看到 Query Router、Conversation Memory、Query Rewrite、Vector、BM25、Hybrid、Rerank、Compression、Final Prompt 每一层发生了什么。
- 专家可以维护评测集，运行冒烟、基准、回归、发布评测。
- 系统可以把 Trace、用户反馈、评测失败沉淀成 Regression Case。
- Agent 可以围绕一次失败问答或失败评测，执行端到端 RAG 修复工作流，并在写操作前等待人工确认。

## 当前能力地图

![AIAssistant RAGOps 当前能力地图](docs/assets/ragops_architecture.png)

## 核心闭环详解

### RAG 问答与可观测链路

这条链路展示一次知识库问答从用户问题进入系统后，如何经过 Query Router、会话记忆、Query Rewrite、Vector/BM25/Hybrid/Rerank、上下文压缩和最终 Prompt，并把每个阶段写入 Trace，支撑后续调试、评测和回归。

![RAG 问答与可观测链路](docs/assets/rag_pipeline_observability.png)

### 评测与回归闭环

评测闭环展示专家 Eval Case 如何按 suite 运行，结合 RAGAS、deterministic checks 和 LLM-as-Judge 生成 Case Result 与 Failure Analysis，再把失败样例、坏 Trace 和用户负反馈沉淀为 Regression Suite，驱动下一轮优化。

![评测与回归闭环](docs/assets/evaluation_regression_loop.png)

### RAGOps Agent 修复闭环

Agent 修复闭环展示系统如何围绕失败 Trace 或 Baseline Eval Run 收集证据、诊断失败阶段、生成优化方案，并通过 Human-in-the-loop Action Card 审批后创建回归样例或运行参数实验计划，形成可审计的自动化修复流程。

![RAGOps Agent 修复闭环](docs/assets/ragops_agent_repair_loop.png)

## 技术栈

- 后端：Django、Django REST Framework、SimpleJWT、SQLite、pytest。
- 前端：Vue 3、Vite 7、Element Plus、Pinia、TypeScript。
- 检索：Milvus Lite 向量索引、SQLite Chunk 元数据、BM25。
- RAG：Query Router、Session Summary Memory、Query Rewrite、Hybrid Search、Rerank、Context Compression、SSE Streaming。
- 评测：RAGAS、轻量后台线程、Eval Run 对比、Failure Analysis。
- Agent：LangGraph、SQLite checkpointer、LangGraph 原生 interrupt/resume、HITL Action Card、Agent 审计记录。
- 模型：通过 `backend/.env` 中的 OpenAI-compatible 配置调用聊天、Embedding、Rerank、Rewrite、Compression。

## 目录结构

```text
AIAssistant/
├── AGENTS.md
├── README.md
├── 一期功能说明.md
├── 二期功能说明.md
├── backend/
│   ├── manage.py
│   ├── assistant_backend/
│   └── rag/
│       ├── agent/              # LangGraph RAGOps Agent（graph / tools / actions / checkpointing）
│       ├── tests/              # P0 核心路径单元测试（RRF、query_router）
│       ├── migrations/
│       ├── services.py         # RAG 主链路 facade（re-export）
│       ├── chat_pipeline.py    # 问答编排
│       ├── retrieval.py        # 检索与 rerank 编排
│       ├── session_memory.py   # 会话摘要记忆
│       ├── indexing.py         # 文档切片与索引
│       ├── hybrid.py           # RRF 融合
│       ├── query_router.py
│       ├── query_rewrite.py
│       ├── eval_runs.py        # Eval Run stale 检测
│       ├── case_factory.py
│       ├── experiments.py
│       └── views.py
└── frontend/
    ├── src/
    │   ├── App.vue             # 工作台壳层
    │   ├── main.ts
    │   ├── api/                # TypeScript API 客户端
    │   ├── composables/        # useAgent / useChat / useEvalRuns 等
    │   ├── stores/             # Pinia（auth 等）
    │   ├── types/
    │   └── components/
    └── package.json
```

## 一期：RAG 系统做了什么

一期目标是把 RAG 链路做成可持续优化的工程系统。

核心能力：

- 知识库管理：创建知识库、上传文档、查看文档和 chunk。
- 五种切片方式：Token、句子、句子窗口、语义、Markdown。
- 向量索引：Chunk 写入 SQLite，Embedding 写入 Milvus Lite。
- Query Router：识别 `internal_knowledge` 和 `web_required`，需要联网/实时信息的问题不会硬查内部知识库。
- 多轮对话：基于当前 ChatSession 最近几轮消息做 Conversational Query Rewrite，解决“他/这个/刚才那个”等指代问题。
- 会话摘要记忆：长对话达到阈值后后台线程生成 Session Summary，后续问题改写会结合摘要和最近几轮消息。
- 混合检索：Vector Search + BM25 Search，通过 RRF 做 Hybrid Fusion。
- Rerank：对 Hybrid 候选重新排序。
- Context Compression：支持结构感知压缩、句子过滤、LLM 压缩等策略。
- SSE 流式回答：右侧对话栏逐 token 输出。
- Trace：保存每次问答的检索、重排、压缩、Prompt、回答和参数。
- 参数调试：前端可调 `chunk_size`、`top_k`、`BM25 top_k`、`RRF_K`、`Rerank top_n`、`Compression`、`Query Rewrite`。
- 成本监控：记录模型调用次数、token、成本、慢请求、失败请求。
- 评测集管理：维护 smoke、benchmark、regression、release。
- 评测报告：保存 RAGAS 分数、Recall@K、Hit Rate、MRR、阶段命中情况。
- Failure Analysis：定位 rewrite、vector、bm25、hybrid、rerank、compression、answer 等失败阶段。
- Eval Run stale 检测：长时间 `running` 的评测 Run 自动标记为 `failed`，避免 UI 假死。
- 回归闭环：从 Trace、Eval Failure、用户负反馈沉淀 Regression Case。
- 核心路径测试：`pytest` 覆盖 RRF 融合与 Query Router，CI 自动运行（`.github/workflows/backend-tests.yml`）。

详细说明见 [一期功能说明.md](./一期功能说明.md)。

## 二期：Agent 工作流做了什么

二期不是给页面堆一堆“Agent 按钮”，而是收敛成一个实用的 RAGOps 工作流：

```text
选择失败 Trace 或 Baseline Eval Run
-> Agent 收集证据
-> 定位失败阶段
-> 生成优化方案
-> human_decision 节点 interrupt（LangGraph checkpoint 暂停）
-> 用户确认 / 拒绝 Action Card
-> LangGraph resume：action_executor 执行写操作 -> responder 生成最终报告
-> 对比 Baseline，推荐 Winner（实验场景）
```

当前 Agent 能力：

- LangGraph 编排：planner、tool executor、diagnostician、proposal、human decision、action executor、responder。
- LangGraph 原生 interrupt/resume：`human_decision` 在创建 Action Card 后 `interrupt()`；confirm/reject 通过 `Command(resume=...)` 恢复图执行。
- SQLite checkpointer：Agent 状态保存在独立 SQLite 文件，不混用 Django `db.sqlite3`。
- Thread ID：前端按 kb/trace/eval/compare 绑定 thread id；支持 `GET /state/` 刷新后恢复中断工作流。
- 轻量状态：Graph state 只保存业务 ID 和必要摘要，不塞大文档、大 chunk 或完整 Trace。
- HITL：创建回归样例、运行实验等写操作必须先生成 Action Card；thread 处于 `awaiting_human` 时，confirm/reject 会触发 graph resume。
- 审计：`RagAgentAction` 保存状态（含 `running`）、结果、错误、来源和创建时间。
- 端到端 RAG 修复入口：前端 Agent 页只保留一个主工作流，不再展示松散的伪需求按钮。

详细说明见 [二期功能说明.md](./二期功能说明.md)。

## 记忆体系

当前系统有三类记忆，边界要区分清楚：

```text
RAG 短期记忆 = 当前 ChatSession 最近几轮消息
RAG 中期记忆 = ChatSessionSummary 会话摘要
RAG 长期知识记忆 = Document / Chunk / Milvus 向量索引
Agent 工作流记忆 = LangGraph SQLite checkpointer
```

`ChatSessionSummary` 由后台线程异步生成，不阻塞 SSE 回答。触发条件默认是：

```text
当前会话消息数 - summary_message_count >= SESSION_SUMMARY_TRIGGER_MESSAGES
```

摘要生成后，下一轮问题改写会同时使用：

```text
Session Summary + 最近几轮消息 + 当前问题
```

右侧 RAG 对话栏会显示“记忆摘要：未触发 / 生成中 / 已启用 / 失败”，中间 Debug 页的 `Conversation Memory` 会展示本次 Trace 是否使用摘要、摘要长度和覆盖消息数。

## 核心 API

基础：

- `POST /api/auth/register/`
- `POST /api/auth/login/`
- `GET /api/auth/me/`
- `POST /api/reset-workspace/`

知识库和文档：

- `/api/knowledge-bases/`
- `/api/documents/`
- `/api/documents/{id}/chunk-preview/`
- `/api/documents/{id}/index/`
- `GET /api/chunk-methods/`

对话和 Trace：

- `/api/chat-sessions/`
- `GET /api/chat-sessions/{id}/messages/`
- `POST /api/chat-sessions/{id}/messages/`
- `POST /api/chat-sessions/{id}/stream/`
- `/api/rag-traces/`

评测：

- `/api/rag-benchmark-cases/`
- `/api/rag-eval-runs/`
- `POST /api/rag-eval-runs/run/`
- `/api/rag-experiment-plans/`

反馈、成本、Agent：

- `/api/rag-user-feedback/`
- `GET /api/model-usage/summary/`
- `POST /api/ragops-agent/run/`
- `GET /api/ragops-agent/state/?thread_id=...`
- `POST /api/ragops-agent/resume/`
- `/api/rag-agent-actions/`
- `POST /api/rag-agent-actions/{id}/confirm/`
- `POST /api/rag-agent-actions/{id}/reject/`

## 数据存在哪里

SQLite `db.sqlite3` 保存业务事实：

- `KnowledgeBase`
- `Document`
- `Chunk`
- `ChatSession`
- `ChatMessage`
- `ChatSessionSummary`
- `RagTrace`
- `RagBenchmarkCase`
- `RagEvalRun`
- `RagEvalCaseResult`
- `RagUserFeedback`
- `RagAgentAction`
- `RagExperimentPlan`

Milvus Lite 保存向量索引，可以从 SQLite 中的 Chunk 和 Embedding 重建。

LangGraph checkpoint 独立保存：

```text
backend/agent_state/langgraph_checkpoints.sqlite3
```

它只保存 Agent 执行状态，不保存业务主事实，不提交 Git。

## 环境变量

后端读取 `backend/.env`。常见配置：

```text
API_KEY=...
API_BASE=...
CHAT_MODEL=qwen-plus
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=1024
DASHSCOPE_API_KEY=...
DEEPSEEK_API_KEY=...
MILVUS_URI=...
MILVUS_COLLECTION=aiassistant_chunks
CONVERSATION_CONTEXT_TURNS=6
SESSION_SUMMARY_ENABLED=true
SESSION_SUMMARY_TRIGGER_MESSAGES=12
SESSION_SUMMARY_MAX_CHARS=2000
EVAL_RUN_STALE_TIMEOUT_SECONDS=3600
LANGGRAPH_CHECKPOINT_DB=...
```

实际配置以 `backend/.env.example` 和 `assistant_backend/settings.py` 为准。

## 启动方式

后端：

```bash
cd /AIAssistant/backend
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8010
```

前端：

```bash
cd /AIAssistant/frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5174
```

访问：

```text
http://localhost:5174
```

## Docker 容器化部署

项目提供一套最小可用的容器化部署：

- `backend/Dockerfile`：Django + Gunicorn，启动时自动执行 `migrate` 和 `collectstatic`。
- `frontend/Dockerfile`：Node 构建 Vue，Nginx 托管静态文件并反代 API。
- `deploy/nginx/aiassistant.docker.conf`：容器内 Nginx 网关配置，SSE 接口关闭缓冲。
- `docker-compose.yml`：编排前端、后端和持久化 volume。

启动：

```bash
cd /home/peng/AIAssistant
docker compose up --build -d
```

访问：

```text
http://127.0.0.1:8080
```

查看日志：

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

停止：

```bash
docker compose down
```

注意：

- 上线前请在 `backend/.env` 中配置真实 `SECRET_KEY`、模型 API Key、模型名称和价格参数。
- SQLite、media、Milvus Lite、LangGraph checkpoint 都通过 Docker volume 持久化。
- 如果要正式公网部署，建议再接入 HTTPS 证书、域名、备份策略和更可靠的数据库。

## Nginx 网关与 SSE 流式输出

如果希望用 Nginx 作为前后端统一入口，推荐让浏览器访问 Nginx，例如：

```text
http://127.0.0.1:8080
```

前端 API 默认走同源 `/api`，因此请求链路变成：

```text
Browser -> Nginx -> Django API
```

开发网关配置：

```bash
sudo nginx -c /home/peng/AIAssistant/deploy/nginx/aiassistant.dev.conf
```

生产式静态前端配置：

```bash
cd /home/peng/AIAssistant/frontend
VITE_API_BASE=/api npm run build
sudo nginx -c /home/peng/AIAssistant/deploy/nginx/aiassistant.prod.conf
```

SSE 流式接口必须关闭 Nginx 响应缓冲，否则浏览器会等后端生成完成后才一次性收到内容。项目配置中已经对聊天流式接口设置：

```nginx
proxy_buffering off;
proxy_cache off;
gzip off;
add_header X-Accel-Buffering no always;
proxy_read_timeout 3600s;
```

当前流式接口路径：

```text
POST /api/chat-sessions/{id}/stream/
```

如果后续新增其它 SSE 接口，也要在 Nginx 中使用同样的关闭缓冲配置。

## 流式输出的生产环境注意事项

SSE 会为每个正在回答的问题维持一个 HTTP 长连接，因此上线时需要同时关注应用层、网关层和系统资源。

后端资源控制：

- `RAG_STREAM_MAX_ACTIVE_PER_PROCESS`：限制每个 Django/Gunicorn 进程内同时活跃的 RAG 流式连接数，超过后返回 `429`。
- `RAG_STREAM_RESPONSE_TIMEOUT_SECONDS`：记录流式响应预期超时时间，和 Nginx/Gunicorn 超时配置保持一致。
- Docker 部署中默认使用 Gunicorn `gthread` worker，相关变量包括 `GUNICORN_WORKERS`、`GUNICORN_THREADS`、`GUNICORN_TIMEOUT`。
- Docker Compose 为 backend 设置了 `nofile` ulimit，避免高并发长连接时过早耗尽文件描述符。

Nginx 网关控制：

- SSE 路径关闭 `proxy_buffering`、`proxy_cache` 和 `gzip`，避免流式响应被缓冲。
- 开发/生产式 Nginx 配置增加了 `limit_conn`，限制单 IP 和单 server 的并发连接数量。
- 高并发部署时需要监控 Nginx active connections、Gunicorn worker/thread 使用率、系统 `open files`。

前端流式渲染：

- 前端优先使用 `ReadableStream + TextDecoderStream` 解码 SSE 文本流。
- 不支持 `TextDecoderStream` 的浏览器会回退到 `ReadableStream.getReader() + TextDecoder`。
- SSE 注释心跳行会被解析器忽略，避免影响业务事件。
- `streamRequest` 支持传入 `AbortController.signal`，后续可用于用户主动停止生成。

## 常用验证命令

后端：

```bash
cd /AIAssistant/backend
source venv/bin/activate
python -m compileall rag assistant_backend
python manage.py check
python manage.py makemigrations --check --dry-run
pytest rag/tests -q
```

前端：

```bash
cd /AIAssistant/frontend
npm run build
```

GitHub Actions（`.github/workflows/backend-tests.yml`）会在 `backend/**` 变更时自动运行上述后端检查与 pytest。

命令行评测：

```bash
cd /AIAssistant/backend
source venv/bin/activate
python manage.py eval_ragas --suite regression
```

## 当前项目价值

这个项目现在具备三条闭环：

1. RAG 调试闭环：问答结果可以回溯到每一层检索和 Prompt。
2. 评测回归闭环：失败可以沉淀成 Regression Case，后续调参可验证。
3. Agent 修复闭环：Agent 诊断问题、生成建议，写操作交给 HITL 确认。

这使它更适合作为简历项目或学习项目里的“RAG 工程化 + RAGOps + Agent 工作流”案例，而不是普通聊天机器人。
