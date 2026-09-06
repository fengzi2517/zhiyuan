<script setup>
import { ref } from 'vue'
import { ChatDotRound, Collection, Files, Setting } from '@element-plus/icons-vue'
import KbManage from './views/KbManage.vue'
import DocManage from './views/DocManage.vue'
import Chat from './views/Chat.vue'
import SettingsDialog from './components/SettingsDialog.vue'

const active = ref('chat')
const settingsVisible = ref(false)

const titles = { chat: '智能问答', kb: '向量库管理', doc: '资料管理' }
const chapters = { chat: '壹', kb: '贰', doc: '叁' }
const subs = {
  chat: '检索增强生成，答案有据可循',
  kb: '知识分库而治，向量聚簇成图',
  doc: '多格式智能解析，中英混检入库',
}
</script>

<template>
  <el-container style="height: 100%">
    <el-aside width="228px" class="sidebar">
      <div class="logo">
        <div class="logo-mark serif">知</div>
        <div class="logo-text">
          <div class="logo-title serif">知源</div>
          <div class="logo-sub">RAG · 检索增强问答</div>
        </div>
      </div>

      <div class="menu-label">目录</div>
      <el-menu :default-active="active" class="side-menu" @select="k => active = k">
        <el-menu-item index="chat">
          <el-icon><ChatDotRound /></el-icon><span>智能问答</span>
        </el-menu-item>
        <el-menu-item index="kb">
          <el-icon><Collection /></el-icon><span>向量库管理</span>
        </el-menu-item>
        <el-menu-item index="doc">
          <el-icon><Files /></el-icon><span>资料管理</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <div class="settings-btn" @click="settingsVisible = true">
          <el-icon><Setting /></el-icon><span>设置</span>
        </div>
        <div class="version">素笺墨线 · v1.2</div>
      </div>
    </el-aside>

    <el-container class="workbench">
      <el-header class="topbar" height="64px">
        <div class="topbar-title-group">
          <span class="chapter serif">{{ chapters[active] }}</span>
          <div>
            <div class="topbar-title serif">{{ titles[active] }}</div>
            <div class="topbar-sub">{{ subs[active] }}</div>
          </div>
        </div>
      </el-header>
      <el-main class="main-area">
        <div class="page-wrap">
          <Chat v-if="active === 'chat'" />
          <KbManage v-else-if="active === 'kb'" />
          <DocManage v-else />
        </div>
      </el-main>
    </el-container>

    <SettingsDialog v-model="settingsVisible" />
  </el-container>
</template>

<style scoped>
.sidebar {
  background: var(--paper-2);
  border-right: 1px solid var(--hairline);
  display: flex;
  flex-direction: column;
  user-select: none;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 22px 20px 18px;
}
.logo-mark {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: var(--seal);
  color: #fdfcf8;
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 0 1.5px rgba(255, 255, 255, 0.28), 0 2px 6px rgba(176, 74, 50, 0.28);
  animation: seal-press 0.5s cubic-bezier(0.2, 1.4, 0.4, 1) both;
}
.logo-title {
  color: var(--ink);
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 0.06em;
}
.logo-sub {
  color: var(--ink-3);
  font-size: 11px;
  margin-top: 3px;
  letter-spacing: 0.05em;
}

.menu-label {
  padding: 6px 24px 4px;
  font-size: 11px;
  color: var(--ink-3);
  letter-spacing: 0.3em;
}

.side-menu {
  border-right: none;
  background: transparent;
  flex: 1;
  padding: 4px 12px 0;
  --el-menu-bg-color: transparent;
  --el-menu-text-color: var(--ink-2);
  --el-menu-hover-bg-color: var(--paper-3);
  --el-menu-active-color: var(--accent-deep);
  --el-menu-item-height: 44px;
}
.side-menu :deep(.el-menu-item) {
  height: 44px;
  margin: 3px 0;
  border-radius: 9px;
  font-size: 14px;
  position: relative;
  transition: background 0.18s ease, color 0.18s ease;
}
.side-menu :deep(.el-menu-item.is-active) {
  background: var(--accent-wash);
  font-weight: 600;
}
.side-menu :deep(.el-menu-item.is-active)::before {
  content: "";
  position: absolute;
  left: 0;
  top: 11px;
  bottom: 11px;
  width: 3px;
  border-radius: 2px;
  background: var(--accent);
}

.sidebar-footer {
  padding: 14px 20px 16px;
  border-top: 1px solid var(--hairline-soft);
}
.settings-btn {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--ink-2);
  cursor: pointer;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13.5px;
  transition: background 0.18s ease, color 0.18s ease;
}
.settings-btn:hover {
  background: var(--paper-3);
  color: var(--ink);
}
.version {
  color: var(--ink-3);
  font-size: 11px;
  margin-top: 8px;
  padding-left: 10px;
  letter-spacing: 0.08em;
}

.workbench { min-width: 0; }

.topbar {
  background: transparent;
  border-bottom: 1px solid var(--hairline);
  display: flex;
  align-items: center;
  padding: 0 28px;
}
.topbar-title-group {
  display: flex;
  align-items: center;
  gap: 14px;
  animation: rise 0.45s ease both;
}
.chapter {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(176, 74, 50, 0.4);
  color: var(--seal);
  border-radius: 50%;
  font-size: 15px;
  font-weight: 600;
  background: rgba(176, 74, 50, 0.04);
}
.topbar-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--ink);
  letter-spacing: 0.05em;
}
.topbar-sub {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-top: 1px;
  letter-spacing: 0.04em;
}

.main-area {
  padding: 0;
  overflow: auto;
  background: transparent;
}
.page-wrap {
  height: 100%;
  padding: 20px 24px 24px;
  display: flex;
  flex-direction: column;
  animation: rise 0.4s ease both;
}
</style>
