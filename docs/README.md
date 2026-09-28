# 技术文档

整理日期：2026-09-28。优先阅读下列指南，本目录按主题归档项目的设计、部署和实验记录。

## 阅读顺序

1. [项目 README](../README.md)：能力、目录、最快本地启动。
2. [部署指南](部署指南.md)：本机与阿里云、环境、模型、账号、备份及排错。
3. [从零复刻技术路线](从零复刻技术路线.md)：从最小问答到持久队列、权限、多模态的阶段验收。

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

`app/graph.py` 是历史 LangGraph 实现，`app/ingest.py` 是早期处理入口；当前持久队列由 `worker.py` 执行，不应把旧文件等同于线上路径。

## 专题

- [多模态聊天与会话附件](多模态聊天与会话附件.md)：具体能力、上限与验证记录。
- [编排与会话工作流](编排与会话工作流.md)：执行器与会话事务设计。
- [部署与任务恢复](部署与任务恢复.md)：早期运维专题；实际部署以新版指南为主。
- [落地验证记录](落地验证记录.md)、[本机入库与延迟修复](本机入库与延迟修复.md)：当时环境与故障处理证据。
- [评测说明](../evaluation/README.md)与[固定基线](../evaluation/reports/baseline-v1/summary.md)：固定检索实验。