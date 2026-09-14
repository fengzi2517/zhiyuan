# 知源前端

Vue 3 + Vite + Element Plus。提供登录、知识库/资料管理、权限、流式问答、模型模式、会话附件和引用抽屉。

```bash
npm ci
npm run dev -- --host localhost --port 5173 --strictPort
```

开发时 API 默认为 `http://当前浏览器hostname:8000`，Cookie 与 CSRF 由 API 客户端管理。后端必须已迁移并启动，入库还需要独立 Worker。

生产构建（Linux Shell）：

```bash
VITE_API_BASE_URL=https://rag.example.com/api npm run build
```

PowerShell 对应：先 `$env:VITE_API_BASE_URL='https://rag.example.com/api'`，再运行 `npm run build`。变量在构建时写入静态资源；不要在发布后仅改服务器环境并期待浏览器自动切换。

`src/api/` 封装接口，`src/composables/useChatStream.js` 处理 SSE，`src/views/Chat.vue` 编排交互，`src/components/AttachmentComposer.vue` 管理附件选择和轮询。`npm test` 执行 Vitest；已有构建大 bundle 提示不等于构建失败。

详见[总 README](../README.md)、[部署指南](../docs/部署指南.md)和[Nginx 配置](../deploy/nginx.conf.example)。
