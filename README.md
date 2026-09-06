# 知源 · RAG 知识库问答系统

本地闭环的企业级 RAG（检索增强生成）系统：上传资料 → 语义切块 → 本地向量化 → pgvector 存储 → 智能问答（附引用来源与完整思维链）。

## 功能特性

- **多格式入库**：PDF（扫描页自动 OCR）、Word（含表格）、图片、TXT/MD（编码自适应）
- **语义切块**：标题感知 + 句子边界 + 块间重叠，不做字符硬切
- **多语言检索**：BGE-M3（1024 维），中英文混检，英文提问可命中中文资料
- **两级检索**：向量召回（HNSW 索引）→ 交叉编码器精排，阈值按实测分数分布校准
- **智能路由**：意图识别三路分发（知识库 / 联网 / 闲聊）；知识库 0 命中自动改写重试，再不足联网兜底
- **思维链可视化**：判定理由、候选相似度、精排分数、兜底路径、各步耗时全程透明
- **多轮会话**：历史持久化 + 分层长期记忆（摘要 + 事实要点），支持编辑/删除消息
- **多库隔离**：按业务线建独立知识库；向量分布 PCA 可视化辅助核验入库质量
- **可私有化**：向量模型/检索/存储全本地，LLM 走 OpenAI 兼容接口可随时替换为私有部署

## 架构

```
上传 ─► 解析(OCR) ─► 语义切块 ─► BGE-M3 向量化 ─► pgvector(HNSW)
                                                        │
提问 ─► 意图识别 ─┬─ 闲聊 ──────────────────► 直接回答    │
                  ├─ 时效 ─► Tavily 联网 ──────┐          │
                  └─ 知识库 ─► 召回粗筛 ─► 精排 ┼─► LLM 生成（附来源）
                              ▲    │0命中      │
                              └改写重试 └─联网兜底┘
```

技术栈：FastAPI · LangGraph · Vue 3 · Element Plus · ECharts · PostgreSQL 18 + pgvector · bge-m3 / bge-reranker-base · RapidOCR · SenseNova (OpenAI 兼容) · Tavily

## 快速启动

### 1. 启动数据库

```bash
docker compose up -d        # pgvector/pgvector:pg18，宿主机 5435 端口
```

### 2. 配置环境变量

```bash
cp .env.example .env        # 填入 LLM_API_KEY 与 TAVILY_API_KEY
```

| 变量 | 说明 |
|---|---|
| DATABASE_URL | pgvector 连接串（默认 localhost:5435） |
| LLM_BASE_URL / LLM_API_KEY / LLM_MODEL | 任意 OpenAI 兼容 LLM（默认 SenseNova flash-lite） |
| TAVILY_API_KEY | [tavily.com](https://tavily.com) 注册免费 1000 次/月；留空自动降级为不联网 |

### 3. 下载本地模型（关键步骤）

模型放 `.hf-cache/`，启动时离线加载（避免弱网下在线检查超时）：

```bash
pip install huggingface_hub
huggingface-cli download BAAI/bge-m3 --local-dir .hf-cache/BAAI/bge-m3
huggingface-cli download BAAI/bge-reranker-base --local-dir .hf-cache/BAAI/bge-reranker-base
```

> 注意：bge-m3 主权重为 `pytorch_model.bin`（约 2.3GB）；PyTorch 2.6+ 若报 weights_only 错误，将其转为 safetensors 即可。详见 [docs/技术报告.md](docs/技术报告.md) 第 5.2 节踩坑清单。

### 4. 启动后端

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

## 使用

1. 「向量库管理」新建知识库 → 「资料管理」上传文档（≤20MB）
2. 「对话」提问：专业问题走知识库检索，时效问题自动联网，闲聊直接回答
3. 展开思维链查看：意图判定理由 → 候选片段相似度 → 精排分数 → 兜底路径 → 各步耗时
4. 顶栏设置可调：检索片段数 top_k、相似度阈值、联网开关

## 测试

后端测试使用项目虚拟环境执行：

```bash
python -m pytest -q
```

前端测试与生产构建：

```bash
cd frontend
npm test
npm run build
```

前端 API 地址可通过 `VITE_API_BASE_URL` 配置，未设置时使用
`http://127.0.0.1:8000`。

## 数据库迁移安全

应用启动时会核对 pgvector 的向量维度。若数据库已有向量维度与
`EMBEDDING_DIM` 不一致，应用会拒绝启动并提示显式迁移，不会自动删除文档。
变更嵌入模型前请先备份数据库，再通过独立迁移或重新建库完成向量重建。

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST /upload | 上传资料（后台异步入库） |
| GET /documents | 文档列表（含处理状态） |
| GET /documents/{id}/content | 查看提取文本 |
| POST /kbs · GET /kbs · DELETE /kbs/{id} | 知识库管理 |
| GET /kbs/{id}/vectors | 向量 PCA 可视化数据 |
| POST /chat | 问答（answer + intent + trace + sources） |
| GET /sessions 等 | 会话/消息/记忆管理 |

完整交互文档见 `http://localhost:8000/docs`（Swagger）。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/技术报告.md](docs/技术报告.md) | 六条核心逻辑链、数据库设计、参数校准、0 到 1 复刻指南、排错档案 |
| [docs/项目成果报告.md](docs/项目成果报告.md) | 面向管理层的项目价值与成果汇报 |
| [docs/面试指南.md](docs/面试指南.md) | 项目面试介绍稿与高频问答 |

## 目录结构

```
app/            后端：parser(解析) chunker(切块) embeddings(向量化/精排)
                graph(LangGraph 编排+trace) llm(意图/记忆) db(ORM/检索) main(API)
frontend/src/   前端：views/Chat(对话) DocManage(资料) KbManage(向量库)
.hf-cache/      本地模型权重（离线加载）
uploads/        上传文件暂存
```

## 已知限制

- 端到端延迟主要取决于 LLM API（当前约 30s），建议更换低延迟模型或流式输出
- 双模型常驻内存约 4GB，16GB 机器需避免与其他大内存进程并发
- 依赖版本未锁定，正式部署建议生成 lock 文件
- 当前入库任务运行在 API 进程内，服务重启可能中断处理中的文档
