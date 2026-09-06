# RAG Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复当前 RAG POC 已复现的安全、终止性、边界数据和会话一致性问题，并建立自动化回归测试。

**Architecture:** 保持现有 FastAPI、LangGraph、SQLAlchemy 和 Vue 结构，将可测试计算提取为纯函数，在 API 边界校验输入，在状态机边界保证终止。前端集中清洗不可信 HTML，并让聊天响应携带持久化消息 ID。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、LangGraph、SQLAlchemy、pytest、Vue 3、Marked、DOMPurify、Vitest、Vite

---

### Task 1: 建立后端测试基线和请求校验

**Files:**
- Create: `tests/test_api_models.py`
- Modify: `app/main.py`
- Modify: `requirements.txt`

- [ ] 写失败测试：空问题、`top_k=0/11`、阈值越界均被 Pydantic 拒绝，合法输入可创建。
- [ ] 运行 `python -m pytest tests/test_api_models.py -v`，确认测试因缺少约束失败。
- [ ] 使用 `Field(min_length=1)`、`field_validator`、`Field(ge=1, le=10)` 和 `Field(ge=0, le=1)` 实现最小约束。
- [ ] 重跑测试并确认通过。

### Task 2: 修复图路由和有限终止

**Files:**
- Create: `tests/test_graph_routing.py`
- Modify: `app/graph.py`

- [ ] 写失败测试：关闭联网的 web 意图不返回 `web_search`；重排降级且 top_k 合法时正常结束；每次无命中都会推进重试。
- [ ] 运行目标测试并确认因当前路由与计数行为失败。
- [ ] 统一联网策略，并让无结果分支统一增加重试次数。
- [ ] 重跑目标测试和后端测试集。

### Task 3: 修复切块和入库状态

**Files:**
- Create: `tests/test_chunker.py`
- Create: `tests/test_ingest.py`
- Modify: `app/chunker.py`
- Modify: `app/ingest.py`
- Modify: `app/db.py`

- [ ] 写失败测试：短文本形成一个块，英文句点可切分，单个超长句有保底切分，空解析/零切块标记失败并记录原因。
- [ ] 运行目标测试并确认失败原因符合预期。
- [ ] 扩展句界正则和保底分割；为 documents 增加 `error_message` 并更新状态接口。
- [ ] 重跑目标测试。

### Task 4: 修复 PCA 边界

**Files:**
- Create: `tests/test_vector_projection.py`
- Modify: `app/main.py`

- [ ] 写失败测试：空、单点、相同向量和普通向量投影均返回合法有限数值。
- [ ] 运行测试并确认单点或零方差失败。
- [ ] 提取 `_project_vectors` 纯函数并处理主成分不足和零方差。
- [ ] 重跑测试。

### Task 5: 修复消息与记忆一致性

**Files:**
- Create: `tests/test_chat_persistence.py`
- Modify: `app/db.py`
- Modify: `app/main.py`
- Modify: `frontend/src/views/Chat.vue`

- [ ] 写失败测试：`save_message` 返回 ID，聊天响应包含两个 ID，删除会话同时删除记忆。
- [ ] 运行测试确认当前实现失败。
- [ ] 返回并透传消息 ID；删除会话时在同一事务删除 SessionMemory。
- [ ] 前端把响应 ID 回填到本地消息对象。
- [ ] 重跑测试和前端构建。

### Task 6: 清理不可信 HTML

**Files:**
- Create: `frontend/src/security.js`
- Create: `frontend/src/security.test.js`
- Modify: `frontend/src/views/Chat.vue`
- Modify: `frontend/src/views/KbManage.vue`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

- [ ] 安装 DOMPurify 和 Vitest，并增加 `test` 脚本。
- [ ] 写失败测试：事件处理器、script、javascript URL 被移除，普通 Markdown 格式保留，tooltip 特殊字符被转义。
- [ ] 运行 Vitest 并确认测试失败。
- [ ] 实现 `renderSafeMarkdown` 和 `escapeHtml`，替换两个直接 HTML 路径。
- [ ] 重跑前端测试。

### Task 7: 禁止启动迁移删数据并补齐工程配置

**Files:**
- Create: `tests/test_schema_safety.py`
- Modify: `app/db.py`
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] 写失败测试：向量维度不匹配时生成明确错误且不执行 DELETE。
- [ ] 运行测试确认当前迁移包含删除行为。
- [ ] 把维度检查改为抛出迁移说明；补充 PyMuPDF、pytest 和忽略项。
- [ ] 更新 README 的测试命令和迁移说明。
- [ ] 重跑测试。

### Task 8: 前端轮询与最终验证

**Files:**
- Modify: `frontend/src/views/DocManage.vue`
- Modify: `frontend/src/api/index.js`

- [ ] 写前端测试或把轮询判定提取为可测纯函数，确认完成后停止轮询。
- [ ] 实现轮询状态收敛和失败原因展示。
- [ ] 运行完整后端测试、前端测试和生产构建。
- [ ] 使用 `git diff --check` 检查补丁格式并审查最终 diff。

