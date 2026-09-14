# 文档与项目结构

文档整理日期：2026-09-14；功能基线 `5dfec36`。优先阅读下列三份指南，历史报告用于了解演进，不代表当前功能或性能承诺。

## 阅读顺序

1. [项目 README](../README.md)：能力、目录、最快本地启动。
2. [部署指南](部署指南.md)：本机与阿里云、环境、模型、账号、备份及排错。
3. [从零复刻技术路线](从零复刻技术路线.md)：从最小问答到持久队列、权限、多模态的阶段验收。
4. [面试指导](面试指导.md)：讲解顺序、追问、简历和故障演示。

## 当前模块地图

| 模块 | 文件 | 主要职责 |
|---|---|---|
| HTTP 入口 | [main.py](../app/main.py) | 上传、模型选项、问答与会话接口 |
| 编排 | [chat_service.py](../app/chat_service.py)、[routing.py](../app/routing.py) | 统一普通/流式阶段执行、证据约束与路由 |
| 权限 | [auth.py](../app/auth.py)、[auth_routes.py](../app/auth_routes.py)、[admin.py](../app/admin.py) | 登录、CSRF、成员与会话归属、管理命令 |
| 存储 | [db.py](../app/db.py)、[migrate.py](../app/migrate.py) | PostgreSQL 模型、事务、记忆快照、schema版本 |
| 文件链路 | [file_pipeline.py](../app/file_pipeline.py)、[parser.py](../app/parser.py)、[chunker.py](../app/chunker.py) | 校验、原件、文本/OCR和位置切块 |
| 模型链路 | [embeddings.py](../app/embeddings.py)、[llm.py](../app/llm.py)、[model_profiles.py](../app/model_profiles.py) | 向量/精排、供应商调用、逐请求参数 |
| 持久任务 | [jobs.py](../app/jobs.py)、[queue_lease.py](../app/queue_lease.py)、[worker.py](../app/worker.py) | 抢占、租约、续期、幂等提交与重试 |
| 会话附件 | [attachments.py](../app/attachments.py)、[attachment_routes.py](../app/attachment_routes.py)、[attachment_context.py](../app/attachment_context.py) | 私有资源、原生视觉/OCR、摘要与片段检索 |
| 可观察与引用 | [operations.py](../app/operations.py)、[sse.py](../app/sse.py)、[sources.py](../app/sources.py) | 健康检查、维护、流事件、引用编号 |
| 界面 | [frontend/src](../frontend/src) | 聊天、附件卡片、资料、权限和引用抽屉 |
| 评测与验证 | [tests](../tests)、[integration_tests](../integration_tests)、[evaluation](../evaluation) | 单元、真实数据库事务、固定检索实验 |

本轮保持 `app/` 和前端源码位置稳定，避免为整理文档改变导入路径。`app/graph.py` 是历史 LangGraph 实现，`app/ingest.py` 是早期处理入口；当前持久队列由 `worker.py` 执行，不应把旧文件等同于线上路径。

## 专题与历史资料

仍适合对照当前实现的专题：

- [多模态聊天与会话附件](多模态聊天与会话附件.md)：具体能力、上限与验证记录。
- [编排与会话工作流](编排与会话工作流.md)：执行器与会话事务设计。
- [部署与任务恢复](部署与任务恢复.md)：早期运维专题；实际部署以新版指南为主。
- [落地验证记录](落地验证记录.md)、[本机入库与延迟修复](本机入库与延迟修复.md)：当时环境与故障处理证据。
- [评测说明](../evaluation/README.md)与[固定基线](../evaluation/reports/baseline-v1/summary.md)：旧版本独立检索实验。

历史报告（不能直接复用其中的性能或能力表述）：

- [技术报告](技术报告.md)、[代码梳理与优化建议](代码梳理与优化建议.md)、[项目成果报告](项目成果报告.md)。
- [旧面试指南](面试指南.md)、[旧 RAG 面试手册](RAG面试实战手册.md)。
- [归档技术评估](archive/技术评估报告.md)：从项目根目录移至 archive。
- [设计记录](superpowers/specs)、[实施记录](superpowers/plans)：按日期留存，不以旧计划代替实际代码。

## 文件清理规则

可再生成的 `.pytest_cache*`、`.test-tmp*`、`__pycache__`、`.pyc`、临时日志和调试 trace 可清理；已合并开发工作树先检查未提交改动和共享目录链接，再注销工作树并删除残余。源码中的临时权重续传脚本已移除，统一按部署指南准备标准缓存。

以下内容不是临时垃圾：`.env`、`.venv`、`.hf-cache`、`uploads`、数据库卷、`frontend/node_modules`、固定评测语料/报告。它们不会随本轮清理删除，也不应提交 Git。现有 `frontend/dist` 是可用的发布产物；需要重新生成时运行 npm build，不将其当源码上传。

`.trae` 是本机工具资料，`FlagEmbedding` 是本机外部源码，均不参与当前应用入口，本轮保留且不发布。Git 内部对象由 Git 自行管理，不手工删除恢复对象。将来决定移除它们时先确认是否有自己的修改。

本轮结构整理新增 `deploy/` 可审阅配置示例、统一 docs 导航和前端说明。应用行为不变，显式补充已使用的 Pillow 依赖；只核对文档链接、配置和发布内容，不重复跑已通过的业务测试。
