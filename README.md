# 知源 · RAG 知识库问答系统

支持本地部署的 RAG（检索增强生成）应用：上传资料 → 可定位切块 → 本地向量化 → pgvector 存储 → 智能路由 → 流式回答（附可点击编号引用）。向量化与存储在本地运行，LLM 和联网搜索取决于配置的服务。

## 编排与会话工作流更新

新增登录与知识库成员权限、PostgreSQL 持久入库队列和独立 Worker。真实数据库并发、跨用户接口权限以及本地 BGE-M3 入库检索已做定向验证。启动前必须运行迁移并创建管理员；详见 [部署与任务恢复](docs/部署与任务恢复.md)。

- 普通与流式问答共用阶段执行器；阶段状态、耗时、运行标识和资料缺失提示可追踪。
- 知识库/网络路径缺少依据时明确说明限制；混合检索保留可用来源；查询改写最多一次。
- 用户与助手消息成对事务提交；记忆任务使用事务内快照和条件写回，防止历史变动后写入旧摘要。
- 编辑助手文本清理该条旧引用，流中断不冒充完整答复。
- 已保存独立合成语料的检索基线；它不代表生产准确率或改造后的端到端表现。

详见 [编排与会话工作流](docs/编排与会话工作流.md)、[检索评测说明](evaluation/README.md) 和 [RAG 面试实战手册](docs/RAG面试实战手册.md)。旧面试文档中的历史耗时数字不能作为当前性能承诺。

## 功能特性

- **多格式入库**：PDF（扫描页自动 OCR）、Word（含表格）、图片、TXT/MD（编码自适应）
- **语义切块**：标题感知 + 句子边界 + 块间重叠，不做字符硬切
- **多语言检索**：BGE-M3（1024 维），中英文混检，英文提问可命中中文资料
- **两级检索**：向量召回（HNSW 索引）→ 交叉编码器精排，阈值按实测分数分布校准
- **智能路由**：语义意图分为闲聊、创作、知识、时效、混合五类；执行统一映射到直接回答、知识库、网络、混合四条路径
- **流式回答**：SSE 依次返回状态、路由、token、来源、处理过程与完成事件，可随时停止
- **编号引用**：正文使用 `[1]`、`[2]`；相同资料复用编号，知识库引用定位原文，网络引用打开原网页
- **过程透明**：只展示可观察的处理阶段、路由理由和耗时，不展示或声称提供模型内部思维链
- **多轮会话**：历史持久化 + 分层长期记忆（摘要 + 事实要点），支持编辑/删除消息
- **多库隔离**：按业务线建独立知识库；向量分布 PCA 可视化辅助核验入库质量
- **可私有化**：向量模型/检索/存储全本地，LLM 走 OpenAI 兼容接口可随时替换为私有部署

## 架构

```
登录/权限校验 ─► 上传持久化 ─► PostgreSQL任务 ─► Worker解析/切块/向量化 ─► pgvector
                                                        │
提问 ─► 结构化语义理解 ─► 确定性路由 ─┬─ direct ────────────┐
                                      ├─ kb ─► pgvector ────┤
                                      ├─ web ─► Tavily ─────┼─► LLM 流式生成 ─► 编号引用
                                      └─ hybrid ─► 两类来源 ┘
```

技术栈：FastAPI · Pydantic 服务编排 · Vue 3 · Element Plus · ECharts · PostgreSQL 18 + pgvector · bge-m3 / bge-reranker-base · RapidOCR · SenseNova (OpenAI 兼容) · Tavily

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
python -m app.migrate
python -m app.admin bootstrap admin
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端运行 `python -m app.worker` 处理入库队列。管理员密码由命令行交互设置，不存在默认密码。前端使用 `localhost:5173`，API 自动匹配 hostname；变更端口时同步更新 TRUSTED_ORIGINS。

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

## 使用

1. 「向量库管理」新建知识库 → 「资料管理」上传文档（≤20MB）
2. 「对话」提问：普通解释和创作直接回答；资料问题检索知识库；时效问题在允许时联网；混合问题合并两类来源
3. 点击正文中的编号或“引用 N 项”打开右侧引用抽屉；知识库资料可定位到页码、章节或字符范围
4. “处理过程”显示用户可观察的阶段和耗时；设置中可控制检索参数、联网、流式显示和长期记忆

旧版本已经入库的文档没有原件路径和精确位置字段。数据库迁移会保留这些数据，但如需页码/章节定位，请重新上传一次文档。

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
| GET /documents/{id}/chunks/{chunk_id}/context | 查看引用片段与位置 |
| GET /documents/{id}/original | 安全读取入库原件 |
| POST /kbs · GET /kbs · DELETE /kbs/{id} | 知识库管理 |
| GET /kbs/{id}/vectors | 向量 PCA 可视化数据 |
| POST /chat | 问答（answer + intent + trace + sources） |
| POST /chat/stream | SSE 流式问答（status / route / token / sources / trace / done） |
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
app/            后端：query_understanding(语义) routing(路由) chat_service(问答)
                sources(引用) sse(流协议) parser/chunker/ingest(可定位入库) db(持久化)
frontend/src/   前端：Chat(流式对话) SourceDrawer/DocumentViewer(引用定位)
                DocManage(资料) KbManage(向量库) SettingsDialog(设置)
.hf-cache/      本地模型权重（离线加载）
uploads/        上传文件暂存
```

## 已知限制

- 端到端总耗时仍主要取决于 LLM API；流式输出降低首字等待，但不会缩短模型总推理时间
- 双模型常驻内存约 4GB，16GB 机器需避免与其他大内存进程并发
- 依赖版本未锁定，正式部署建议生成 lock 文件
- 当前入库任务运行在 API 进程内，服务重启可能中断处理中的文档
