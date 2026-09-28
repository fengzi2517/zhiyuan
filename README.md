# 知源 (Zhiyuan)

一个支持知识库检索与会话私有附件的多模态 RAG 应用。后端使用 FastAPI + PostgreSQL（pgvector），前端使用 Vue 3 + Element Plus，支持 SSE 流式输出、来源引用与会话级附件（图片/PDF 等）。文档处理由独立的持久化 Worker 执行，资料不足时明确说明限制并按需启用联网核验。

> 仓库对应代码不包含任何 API Key、用户文档或隐私数据；运行前请按 `.env.example` 准备本地配置。

## 一、能力概览

- **多格式资料入库**：PDF（含扫描件 OCR）、DOCX、TXT、Markdown、图片；保留页码、章节、字符范围等定位信息。
- **多语言检索**：BGE-M3（1024 维）多语言向量 + BGE reranker-base 交叉编码器精排；支持中英混合。
- **意图与路由**：闲聊 / 创作 / 知识 / 时效 / 混合五种意图，落地为 direct、kb、web、hybrid 四条路径。
- **持久任务队列**：PostgreSQL 行锁 + 租约续期 + 领取令牌校验，崩溃恢复后任务可被重新领取，不重复入库。
- **会话私有附件**：原生视觉理解 / OCR / 长附件摘要 / 片段检索，按用户会话隔离，不进入共享知识库。
- **可观察性**：理解、路由、检索、重排、改写、联网、生成各阶段耗时与状态通过 SSE 推送到前端。
- **流式输出与引用**：逐 token 流式生成，引用编号可在前端点击回溯到原文位置。

## 二、技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI、Uvicorn、SQLAlchemy、Psycopg |
| 存储 | PostgreSQL 16 + pgvector（HNSW 索引） |
| 向量模型 | BAAI/bge-m3（本地，CPU 可跑） |
| 重排模型 | BAAI/bge-reranker-base（本地） |
| OCR | RapidOCR（onnxruntime） |
| 联网 | Tavily Search API |
| 前端 | Vue 3、Vite、Element Plus、ECharts、Marked、DOMPurify |
| 测试 | Pytest、Vitest |

## 三、架构设计

### 3.1 顶层数据流

```
        ┌─────────────┐
        │  Vue 3 SPA  │  Element Plus / ECharts / SSE
        └──────┬──────┘
               │ HTTPS (cookie + CSRF)
        ┌──────▼──────────────────────────────────────┐
        │             FastAPI (app/main.py)           │
        │  upload · chat · session · admin · ops API  │
        └──────┬──────────────────────────────────────┘
               │
   ┌───────────┼─────────────┬──────────────────────┐
   ▼           ▼             ▼                      ▼
┌──────┐  ┌─────────┐  ┌────────────┐         ┌─────────┐
│ Auth │  │ Chat    │  │ File       │         │ Sources │
│ + DB │  │ Service │  │ Pipeline   │         │ / SSE   │
│ 事务 │  │ 编排    │  │ + Worker   │         │ 流事件  │
└──┬───┘  └────┬────┘  └──────┬─────┘         └────┬────┘
   │           │             │                     │
   ▼           ▼             ▼                     ▼
PostgreSQL (pgvector) ──────► BGE-M3 + bge-reranker ──► LLM (OpenAI 兼容)
   文档/块/向量/任务/会话/记忆    Tavily (可选)            ↑↓
                                                          SSE 阶段事件
```

### 3.2 模块职责

| 层 | 关键文件 | 职责 |
|---|---|---|
| HTTP 入口 | `app/main.py` | FastAPI 路由：上传、模型选项、问答与会话接口 |
| 编排 | `app/chat_service.py`、`app/routing.py` | 统一普通/流式阶段执行、证据约束与路由 |
| 权限 | `app/auth.py`、`app/auth_routes.py`、`app/admin.py` | 登录、CSRF、成员与会话归属、管理命令 |
| 存储 | `app/db.py`、`app/migrate.py` | PostgreSQL 模型、事务、记忆快照、schema 版本 |
| 文件链路 | `app/file_pipeline.py`、`app/parser.py`、`app/chunker.py` | 校验、原件、文本/OCR 和位置切块 |
| 模型链路 | `app/embeddings.py`、`app/llm.py`、`app/model_profiles.py` | 向量/精排、供应商调用、逐请求参数 |
| 持久任务 | `app/jobs.py`、`app/queue_lease.py`、`app/worker.py` | 抢占、租约、续期、幂等提交与重试 |
| 会话附件 | `app/attachments.py`、`app/attachment_routes.py`、`app/attachment_context.py` | 私有资源、原生视觉/OCR、摘要与片段检索 |
| 可观察与引用 | `app/operations.py`、`app/sse.py`、`app/sources.py` | 健康检查、维护、流事件、引用编号 |
| 界面 | `frontend/src` | 聊天、附件卡片、资料、权限和引用抽屉 |
| 评测 | `tests/`、`integration_tests/`、`evaluation/` | 单元、真实数据库事务、固定检索实验 |

### 3.3 关键技术决策

- **不使用 Redis/Celery，持久化任务跑在 PostgreSQL**：`SKIP LOCKED` 行锁领取 + 租约续期 + 领取令牌校验即可恢复崩溃 Worker，事务一致性更简单（块、文本、状态一起提交）。
- **意图与路由解耦**：`query_understanding` 只输出结构化结果（意图、是否需要知识库、是否需要联网、改写查询），由 `routing` 的纯函数映射到 `direct` / `kb` / `web` / `hybrid` 四条路径——前者方便调试和回放，后者方便单独验证策略。
- **BGE-M3 仅使用 dense 向量**：1024 维 pgvector 存储，HNSW 索引；交叉编码器 `bge-reranker-base` 仅在候选上精排，不替代召回。
- **同步 / 流式问答共用同一执行体**：`/chat` 与 `/chat/stream` 都走 `ChatService.execute`，避免实现漂移。
- **引用编号稳定**：相同来源在同一次回答中复用同一编号，`sources.py` 校验位置字段且前后端约定口径。

## 四、核心机制

### 4.1 持久入库与任务恢复（worker）

```
客户端上传 ─► file_pipeline 校验写入文档与 jobs 记录（事务内）
                │
                ▼
   jobs.status=queued ─► worker.poll() ─►
        BEGIN;
        SELECT … FROM jobs
         WHERE status='queued'
         ORDER BY id
         FOR UPDATE SKIP LOCKED
         LIMIT 1;          ─► lease_token=A, lease_until=t+120s
        …
        解析 → 切块 → BGE-M3 编码
        INSERT chunks / chunk_text / job_events;
        UPDATE jobs SET status='running', progress=…;
        COMMIT;
        ─► 周期性续期 lease_until=t+120s；
           worker 崩溃则后续 worker 用不同 lease_token 接管
        解析完成 → status='succeeded'；
        失败 → 计数 +1 直到 attempts>max_attempts 进入 failed
```

关键不变量：文档块、正文、任务状态在同一事务内写入，避免半成品数据被前端检索到。

### 4.2 问答编排（chat_service）

```
HTTP /chat (或 /chat/stream)
        │
        ▼
理解 ─► query_understanding.understand(question, history)
        │  返回 IntentResult(intent, kb_required, web_required, rewrite)
        ▼
路由 ─► routing.decide(intent, kb_available, web_enabled)
        │  返回 RoutePath ∈ {direct, kb, web, hybrid}
        ▼
检索 (kb / hybrid) ─► search.retrieve(rewrite)
        │  向量召回 top-N，按阈值筛选
        ▼
精排 ─► embeddings.rerank(query, candidates)
        │  按 rerank 阈值筛选，留 K 个
        ▼
证据为空 ─► 最多一次 query 改写并重试一次
        ▼
拼接上下文 ─► llm.stream(question, context, history, profile)
        │  SSE 推送 status → route → token* → sources → trace → done
        ▼
持久化 ─► chat/turn 写入 PostgreSQL（事务），记忆快照条件写回
```

### 4.3 会话私有附件

- 上传时打 `conversation_id` 标签，独立附件表，不参与知识库向量召回。
- 三种使用模式：原生视觉（图片直接喂给 LLM）、OCR 转文本、长附件走"分组遍历 + 摘要 + 片段检索"组合。
- 全文摘要受时间窗与调用次数限制，不把 top-K 片段冒充全文。

### 4.4 安全与会话归属

- 登录使用 bcrypt + 失败计数窗口，`SESSION_HOURS` 控制有效期；Cookie `HttpOnly + SameSite=Lax`，CSRF token 校验写入类请求。
- `auth.py` 的 `current_user` 与会话所有权检查覆盖上传、问答、附件、记忆回写。
- `.env.example` 中给出 `TRUSTED_ORIGINS`，生产部署必须替换为强密码与独立数据库。

### 4.5 多模态与模型策略

- `model_profiles.py` 注册可用模型（id、name、model、vision、fast/deep 参数）；前端只发送 id，密钥与地址不下发。
- 不同请求可在 fast / deep 之间切换（如开启/关闭推理），按请求传入到 `llm.stream`。
- 图片是否原生走视觉由当前 profile 的 `vision` 决定；非视觉路径自动降级到 OCR + 文本。

## 五、数据库 Schema 概览

主要表（详见 `app/db.py` / `app/migrate.py`）：

- `users`：账号、密码哈希、失败计数、锁定时间。
- `documents`：知识库文档元数据 + 状态 + 来源文件名。
- `chunks`：向量块（pgvector 1024 维 + 位置字段：page、heading、char_start/end）。
- `chunk_text`：与 chunks 1:1 的全文（拆分存储便于备份/索引）。
- `jobs`：入库任务（status、attempts、lease_token、lease_until、progress）。
- `chat_sessions` / `chat_messages`：会话与消息，支持事务成对写入。
- `memory_snapshots`：分层记忆快照，条件写回避免历史编辑后旧记忆复活。
- `attachments` / `attachment_fragments`：会话私有附件与片段。
- `kb_memberships`：知识库成员关系（会话归属）。

## 六、仓库结构

```
.
├── app/                  # FastAPI 后端（HTTP 入口、编排、存储、模型调用、Worker）
├── frontend/             # Vue 3 + Vite 前端
├── deploy/               # 部署相关配置示例（nginx 等）
├── docs/                 # 技术文档与设计记录
├── evaluation/           # 固定合成语料的离线检索实验
├── tests/                # 单元测试
├── integration_tests/    # 集成测试（需真实 PostgreSQL）
├── scripts/              # 一次性运维脚本
├── compose.integration.yml
├── docker-compose.yml
├── docker-compose.deploy.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

更详细的模块索引、字段定义和阶段验收参见 [`docs/README.md`](docs/README.md)。

## 七、最快本地启动

依赖：Python 3.11+、Node.js 20+、PostgreSQL 16（启用 pgvector 扩展）。

### 7.1 准备环境

```bash
# 后端依赖
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 前端依赖
cd frontend
npm install
```

### 7.2 准备 PostgreSQL

确保本地 PostgreSQL 已启用 `vector` 扩展，并创建 `rag` 库与同名用户（默认连接 `127.0.0.1:5435`，用户名 `rag`，密码 `rag`，可在 `.env` 中修改）。

### 7.3 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少设置 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / TAVILY_API_KEY
```

`LLM_*` 兼容任意 OpenAI 协议的 Chat Completions 接口；视觉能力依赖所选模型是否原生支持图片输入。

### 7.4 准备 BGE 模型

首次运行会自动从 HuggingFace 下载 `BAAI/bge-m3` 与 `BAAI/bge-reranker-base` 到 `.hf-cache/`。如网络受限，可预先下载并把缓存目录指向已有路径。

### 7.5 初始化数据库与启动

```bash
python -m app.migrate        # 应用 schema 迁移
python -m app.worker &      # 启动持久任务 Worker（前台/后台均可）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 7.6 启动前端

```bash
cd frontend
npm run dev
```

默认地址：

- 后端 API：http://localhost:8000
- 前端开发页：http://localhost:5173

## 八、测试

```bash
# 单元测试（无需数据库）
pytest -m "not integration" tests/

# 集成测试（需要本地 PostgreSQL）
docker compose -f compose.integration.yml up -d
pytest integration_tests/
```

离线检索实验（不调用 LLM、Tavily，只读取本地 HuggingFace 缓存）：

```bash
python -m evaluation.run --model-cache .hf-cache --output evaluation/reports/new-run
```

详见 [`evaluation/README.md`](evaluation/README.md)。

## 九、部署

`deploy/` 提供 nginx 反代示例，`docker-compose.deploy.yml` 用于阿里云部署。生产部署请使用强密码与独立数据库，并按 [`docs/部署指南.md`](docs/部署指南.md) 完成前置准备。

## 十、不提交到仓库的内容

以下内容仅在本地使用，已通过 `.gitignore` 排除，**不会**出现在 GitHub：

- `.env`、`uploads/`、`.venv/`、`.hf-cache/`、`frontend/node_modules/`、`frontend/dist/`
- `FlagEmbedding/`（本地外部源码副本）、`.trae/`（本机工具资料）
- `evaluation/reports/`（每次重新运行都会生成）