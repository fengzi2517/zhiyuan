# Intent, Streaming, Citations, and Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将查询语义与执行路由分离，提供带去重引用的流式回答和可恢复历史，并按双栏加引用抽屉方案优化四个桌面页面。

**Architecture:** 后端新增独立的查询理解、路由策略、来源编号和问答服务模块；现有 LangGraph 只编排这些明确接口。数据库以可空字段兼容扩展元数据，FastAPI 通过 SSE 暴露流式事件；Vue 客户端用组合式模块消费事件并驱动双栏界面。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、LangGraph、SQLAlchemy、pgvector、OpenAI-compatible SDK、pytest、Vue 3、Element Plus、Vitest、Vite

---

## 文件职责

- `app/query_understanding.py`：语义意图模型、确定性信号、结构化 LLM 分类。
- `app/routing.py`：无副作用的执行路径策略。
- `app/sources.py`：来源对象、去重编号、引用校验。
- `app/chat_service.py`：同步与流式问答共用的业务服务。
- `app/sse.py`：SSE 序列化，不包含业务判断。
- `app/parser.py`、`app/chunker.py`、`app/ingest.py`：产生并保存页码、章节和字符位置。
- `app/db.py`：兼容 schema 扩展、结构化检索结果、消息运行元数据。
- `app/main.py`：HTTP 请求校验、普通响应、流式响应、原文访问。
- `frontend/src/composables/useChatStream.js`：SSE 消费和状态归并。
- `frontend/src/components/SourceDrawer.vue`：编号来源、定位和外链。
- `frontend/src/components/ProcessTrace.vue`：处理阶段与耗时。
- `frontend/src/components/DocumentViewer.vue`：PDF 页定位或提取文本高亮。
- 四个 `views/*.vue`：页面编排，不承载协议解析。

### Task 1: 兼容数据模型与迁移

**Files:**
- Modify: `app/db.py`
- Create: `tests/test_metadata_migrations.py`
- Modify: `tests/test_chat_persistence.py`

- [ ] **Step 1: 写失败测试**

测试 `Chunk` 暴露 `page_start/page_end/section/start_char/end_char`，`Document` 暴露 `storage_path`，`ChatMessage` 暴露 `semantic_intent/route/sources/trace/elapsed_ms/status`；测试迁移 SQL 只含 `ADD COLUMN IF NOT EXISTS`，不含 `DROP` 或 `DELETE`。

```python
def test_metadata_columns_exist():
    assert hasattr(db.Chunk, "page_start")
    assert hasattr(db.ChatMessage, "sources")

def test_metadata_migration_is_additive():
    sql = "\n".join(db.metadata_migration_statements())
    assert "ADD COLUMN IF NOT EXISTS" in sql
    assert "DELETE " not in sql.upper()
    assert "DROP " not in sql.upper()
```

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_metadata_migrations.py tests/test_chat_persistence.py -q`  
Expected: FAIL，缺少字段和 `metadata_migration_statements`。

- [ ] **Step 3: 最小实现**

使用 SQLAlchemy `JSON` 和可空列；迁移语句由纯函数返回并在 `init_db()` 中逐条执行。扩展 `save_message(..., metadata=None)` 与 `get_session_messages()`，旧消息的 JSON 字段返回空列表。

- [ ] **Step 4: 验证绿灯并提交**

Run: `python -m pytest tests/test_metadata_migrations.py tests/test_chat_persistence.py -q`  
Expected: PASS。  
Commit: `feat: persist chat runs and source metadata`

### Task 2: 解析、切块与原文定位元数据

**Files:**
- Modify: `app/parser.py`
- Modify: `app/chunker.py`
- Modify: `app/ingest.py`
- Modify: `app/db.py`
- Create: `tests/test_document_metadata.py`

- [ ] **Step 1: 写失败测试**

```python
def test_pdf_pages_retain_page_numbers(pdf_bytes):
    pages = parse_file_units("guide.pdf", pdf_bytes)
    assert [page.page for page in pages] == [1, 2]

def test_chunks_retain_location():
    chunks = chunk_units([ParsedUnit(text="# 标题\n正文", page=3, start_char=20)])
    assert chunks[0].page_start == 3
    assert chunks[0].section == "标题"
    assert chunks[0].start_char == 20
```

另测上传原始文件使用 `uploads/<doc_id>/source.<ext>`，路径由服务端生成，不能包含用户文件名中的目录片段。

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_document_metadata.py -q`  
Expected: FAIL，缺少 `ParsedUnit`、`chunk_units` 和安全存储函数。

- [ ] **Step 3: 最小实现**

增加 `ParsedUnit` 与 `ChunkData` dataclass；PDF 每页生成单元，其他格式生成页码为空的单元。`chunk_units` 复用现有切分并传播页码、章节和字符范围。`process_file` 保存原始字节并调用 `save_chunks` 写入结构化字段。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest tests/test_document_metadata.py tests/test_chunker.py tests/test_ingest.py -q`  
Expected: PASS。  
Commit: `feat: retain document locations during ingestion`

### Task 3: 结构化查询理解

**Files:**
- Create: `app/query_understanding.py`
- Modify: `app/llm.py`
- Create: `tests/test_query_understanding.py`

- [ ] **Step 1: 写固定问题表失败测试**

```python
@pytest.mark.parametrize("question,intent", [
    ("你好", "chitchat"),
    ("帮我润色这段话", "create"),
    ("解释一下向量数据库", "knowledge"),
    ("今天人民币汇率是多少", "current"),
    ("结合公司制度和最新法规给建议", "mixed"),
])
def test_deterministic_signals(question, intent):
    assert detect_explicit_intent(question) == intent
```

测试结构化响应缺字段、非法枚举和置信度越界时返回明确降级结果，而不是正则截取任意 JSON。

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_query_understanding.py -q`  
Expected: FAIL，模块不存在。

- [ ] **Step 3: 最小实现**

定义：

```python
class QueryUnderstanding(BaseModel):
    semantic_intent: Literal["chitchat", "create", "knowledge", "current", "mixed"]
    query: str = Field(min_length=1)
    needs_kb: bool
    needs_web: bool
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=100)
```

明确规则直接返回；模糊问题调用支持 JSON Schema 的 chat completion，验证失败返回 `knowledge`、原 query、低置信度与降级原因。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest tests/test_query_understanding.py -q`  
Expected: PASS。  
Commit: `feat: add structured query understanding`

### Task 4: 确定性执行路由

**Files:**
- Create: `app/routing.py`
- Create: `tests/test_routing_policy.py`

- [ ] **Step 1: 写路由矩阵失败测试**

覆盖：闲聊与创作走 direct；current 走 web；mixed 走 hybrid；选中知识库的 knowledge 走 kb；无知识库的 knowledge 在允许联网时走 web、关闭联网时走 direct；关闭联网的 mixed 降为 kb；低置信度且有知识库时走 kb。

```python
def test_web_switch_is_absolute():
    decision = decide_route(mixed_result, RouteContext(has_kb=True, web_enabled=False))
    assert decision.route == "kb"
    assert decision.needs_web is False
```

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_routing_policy.py -q`  
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现纯函数并验证**

`decide_route(understanding, context) -> RouteDecision` 不访问数据库、LLM 或网络；所有联网策略只在此处解释。

- [ ] **Step 4: 提交**

Run: `python -m pytest tests/test_routing_policy.py -q`  
Expected: PASS。  
Commit: `feat: centralize answer routing policy`

### Task 5: 结构化检索结果与引用编号

**Files:**
- Create: `app/sources.py`
- Modify: `app/db.py`
- Modify: `app/search.py`
- Modify: `app/embeddings.py`
- Create: `tests/test_sources.py`

- [ ] **Step 1: 写失败测试**

测试知识库检索返回 `chunk_id/document_id/title/location/score/content`；网络 URL 去掉 fragment 并规范化；同一 source key 只分配一个编号；`[9]` 等不存在引用会被移除；响应只保留实际引用来源。

```python
def test_duplicate_source_reuses_number():
    numbered = number_sources([source_a, source_a, source_b])
    assert [item.number for item in numbered] == [1, 2]
```

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_sources.py -q`  
Expected: FAIL，来源 API 尚不存在。

- [ ] **Step 3: 最小实现**

定义 `Source` Pydantic 模型、`deduplicate_sources()`、`number_sources()` 和 `validate_answer_citations()`。修改检索函数返回字典对象，reranker 保留元数据只更新分数。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest tests/test_sources.py -q`  
Expected: PASS。  
Commit: `feat: add stable numbered citations`

### Task 6: 重构问答编排与同步兼容接口

**Files:**
- Create: `app/chat_service.py`
- Modify: `app/graph.py`
- Modify: `app/main.py`
- Modify: `tests/test_graph_routing.py`
- Create: `tests/test_chat_service.py`

- [ ] **Step 1: 写失败测试**

用依赖注入替身验证 direct、kb、web、hybrid 四条路径；hybrid 同时调用两类检索；知识库二次无命中后按语义而不是旧 `intent` 降级；每条路径有限结束。

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_chat_service.py tests/test_graph_routing.py -q`  
Expected: FAIL，服务和新状态字段不存在。

- [ ] **Step 3: 最小实现**

`ChatService.run()` 返回 `ChatResult`；LangGraph state 使用 `understanding` 和 `route_decision`，删除节点内分散的联网判断。上下文按编号来源构造，并要求模型只使用 `[n]` 引用。`/chat` 调用服务并保持现有字段，同时增加新字段。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest tests/test_chat_service.py tests/test_graph_routing.py tests/test_chat_persistence.py -q`  
Expected: PASS。  
Commit: `refactor: separate query intent from execution route`

### Task 7: SSE 流式回答

**Files:**
- Create: `app/sse.py`
- Modify: `app/llm.py`
- Modify: `app/chat_service.py`
- Modify: `app/main.py`
- Create: `tests/test_chat_stream.py`

- [ ] **Step 1: 写失败测试**

测试正常事件顺序包含 `status → route → token* → sources → trace → done`；LLM 异常以 `error` 结束；客户端取消后生成器关闭；只有完整结果以 done 状态持久化。

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_chat_stream.py -q`  
Expected: FAIL，`/chat/stream` 和 SSE 编码器不存在。

- [ ] **Step 3: 最小实现**

`encode_sse(event, data)` 使用 JSON UTF-8；LLM 包装增加 token iterator；`StreamingResponse` 设置 `text/event-stream`、`Cache-Control: no-cache` 和 `X-Accel-Buffering: no`。服务在 `finally` 中关闭上游流。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest tests/test_chat_stream.py -q`  
Expected: PASS。  
Commit: `feat: stream chat progress and answer tokens`

### Task 8: 原文查看与定位 API

**Files:**
- Modify: `app/main.py`
- Modify: `app/db.py`
- Create: `tests/test_document_viewer_api.py`

- [ ] **Step 1: 写失败测试**

测试 chunk context 端点返回安全的文档元数据和位置；原始文件端点只读取数据库保存路径且路径必须位于 `uploads/<doc_id>`；不存在和越界定位返回 404/409。

- [ ] **Step 2: 验证红灯**

Run: `python -m pytest tests/test_document_viewer_api.py -q`  
Expected: FAIL，端点不存在。

- [ ] **Step 3: 最小实现并验证**

增加 `/documents/{doc_id}/chunks/{chunk_id}/context` 和 `/documents/{doc_id}/original`。PDF 响应支持前端页码参数；其他文件返回提取文本和 highlight 范围。

- [ ] **Step 4: 提交**

Run: `python -m pytest tests/test_document_viewer_api.py -q`  
Expected: PASS。  
Commit: `feat: open cited documents at matched locations`

### Task 9: 前端流式客户端与可恢复消息

**Files:**
- Create: `frontend/src/composables/useChatStream.js`
- Create: `frontend/src/composables/useChatStream.test.js`
- Modify: `frontend/src/api/index.js`
- Modify: `frontend/src/views/Chat.vue`

- [ ] **Step 1: 写失败测试**

测试分块 SSE 跨网络 chunk 拼接、各事件归并、error 结束 loading、AbortController 取消旧请求，以及历史消息 sources/trace/elapsed_ms/status 映射。

- [ ] **Step 2: 验证红灯**

Run: `npm test -- src/composables/useChatStream.test.js`  
Expected: FAIL，模块不存在。

- [ ] **Step 3: 最小实现**

使用 `fetch` + `ReadableStream` 解析 SSE；组合式函数维护 `phase/content/sources/trace/error`。`Chat.vue` 不再等待单个 Axios 响应，而是逐事件更新当前助手消息。

- [ ] **Step 4: 验证并提交**

Run: `npm test -- src/composables/useChatStream.test.js`  
Expected: PASS。  
Commit: `feat: consume streaming chat events`

### Task 10: 双栏加引用抽屉聊天界面

**Files:**
- Create: `frontend/src/components/SourceDrawer.vue`
- Create: `frontend/src/components/ProcessTrace.vue`
- Create: `frontend/src/components/DocumentViewer.vue`
- Create: `frontend/src/components/SourceDrawer.test.js`
- Modify: `frontend/src/views/Chat.vue`
- Modify: `frontend/src/style.css`

- [ ] **Step 1: 写失败组件测试**

测试相同来源只显示一次、编号点击打开对应项、知识库来源触发内嵌查看、网络来源设置安全外链属性、处理阶段显示用户可观察信息且不使用“思维链”文案。

- [ ] **Step 2: 验证红灯**

Run: `npm test -- src/components/SourceDrawer.test.js`  
Expected: FAIL，组件不存在。

- [ ] **Step 3: 实现 B 布局**

保留左侧会话和主回答区；来源按钮打开右侧抽屉，支持固定。正文 `[n]` 转换为可点击引用标记。加载区域显示阶段进度，首 token 后展示光标动画，完成后展示耗时。

- [ ] **Step 4: 验证并提交**

Run: `npm test`  
Expected: PASS。  
Commit: `feat: add citation drawer and process timeline`

### Task 11: 优化知识库、资料与设置页面

**Files:**
- Modify: `frontend/src/views/KbManage.vue`
- Modify: `frontend/src/views/DocManage.vue`
- Modify: `frontend/src/components/SettingsDialog.vue`
- Modify: `frontend/src/settings.js`
- Create: `frontend/src/settings.test.js`

- [ ] **Step 1: 写失败测试**

测试设置兼容旧 localStorage、流式默认开启、联网开关保持最高优先级；资料状态统计和失败重试派生值正确。

- [ ] **Step 2: 验证红灯**

Run: `npm test -- src/settings.test.js`  
Expected: FAIL，缺少新设置与派生逻辑。

- [ ] **Step 3: 最小实现**

设置按三组展示；资料页增加统计和重试入口；知识库卡片统一状态层级、操作反馈与最近更新时间。保持浅色主题和桌面信息密度。

- [ ] **Step 4: 验证并提交**

Run: `npm test && npm run build`  
Expected: PASS；仅允许已记录的 bundle size 警告。  
Commit: `feat: refine knowledge and document workflows`

### Task 12: 文档、全链路验证与收尾

**Files:**
- Modify: `README.md`
- Modify: `docs/技术报告.md`
- Modify: `docs/面试指南.md`
- Modify: `docs/代码梳理与优化建议.md`

- [ ] **Step 1: 更新实际架构文档**

记录五类语义意图、四条执行路径、SSE 事件、引用格式、旧资料重入库要求、数据库兼容迁移和运行命令；删除“完整思维链”表述，统一为“处理过程”。

- [ ] **Step 2: 后端完整验证**

Run: `python -m pytest -q`  
Expected: 全部通过，0 failed。

- [ ] **Step 3: 前端完整验证**

Run: `npm test && npm run build`  
Expected: 全部通过且构建成功。

- [ ] **Step 4: 静态与 Git 检查**

Run: `python -m compileall -q app tests`、`git diff --check`、`git status --short`。  
Expected: 编译和 diff 检查退出码 0，只显示计划内文件。

- [ ] **Step 5: 提交文档**

Commit: `docs: describe routed streaming rag workflow`

