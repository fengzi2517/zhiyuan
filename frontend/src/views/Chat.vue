<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, Delete, Edit, Plus, Promotion, VideoPause } from '@element-plus/icons-vue'
import { renderSafeMarkdown } from '../security'
import { chat, listKbs, listSessions, getSessionMessages, deleteSession, editMessage, getSessionMemory } from '../api'
import { settings } from '../settings'
import { useChatStream } from '../composables/useChatStream'
import ProcessTrace from '../components/ProcessTrace.vue'
import SourceDrawer from '../components/SourceDrawer.vue'

const kbs = ref([]), sessions = ref([]), messages = ref([])
const currentSession = ref(''), selectedKb = ref(null), input = ref('')
const sending = ref(false), listRef = ref(null), memoryVisible = ref(false)
const memoryData = ref({ summary: '', facts: '' })
const drawerOpen = ref(false), drawerSources = ref([]), activeCitation = ref(null)
const { start: startStream, cancel: cancelStream } = useChatStream()
const routeLabels = { direct: '直接回答', kb: '知识库', web: '网络检索', hybrid: '资料＋网络' }
const phaseLabels = { understanding: '正在理解问题', generating: '正在组织回答' }

const newSessionId = () => `s${Date.now().toString(36)}`
const scrollToBottom = () => nextTick(() => { if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight })
const loadKbs = async () => { kbs.value = await listKbs() }
const loadSessions = async () => { sessions.value = await listSessions() }

async function openSession(sid) {
  cancelStream(); sending.value = false; currentSession.value = sid
  const rows = await getSessionMessages(sid)
  messages.value = rows.map(row => ({
    id: row.id, role: row.role, content: row.content, route: row.route,
    intent: row.semantic_intent, sources: row.sources || [], trace: row.trace || [],
    elapsedMs: row.elapsed_ms, status: row.status,
  }))
  drawerOpen.value = false; scrollToBottom()
}

function newChat() {
  cancelStream(); sending.value = false; currentSession.value = newSessionId()
  messages.value = []; drawerOpen.value = false
}

async function removeSession(sid) {
  await ElMessageBox.confirm('删除该会话的全部历史记录？', '删除确认', { type: 'warning' })
  await deleteSession(sid)
  if (currentSession.value === sid) newChat()
  await loadSessions()
}

async function send() {
  const question = input.value.trim()
  if (!question || sending.value) return
  if (!currentSession.value) currentSession.value = newSessionId()
  input.value = ''
  const userMessage = { role: 'user', content: question }
  const pending = { role: 'assistant', content: '', sources: [], trace: [], loading: true, phase: 'understanding' }
  messages.value.push(userMessage, pending); sending.value = true; scrollToBottom()
  const payload = {
    question, session_id: currentSession.value, kb_id: selectedKb.value,
    top_k: settings.topK, web_enabled: settings.webEnabled,
    sim_threshold: settings.simThreshold, use_memory: settings.useMemory,
  }
  if (!settings.streamEnabled) {
    try {
      const result = await chat(question, currentSession.value, { kbId: selectedKb.value, topK: settings.topK, webEnabled: settings.webEnabled, simThreshold: settings.simThreshold, useMemory: settings.useMemory })
      Object.assign(pending, { content: result.answer, route: result.route, intent: result.semantic_intent, sources: result.sources || [], trace: result.trace || [], elapsedMs: result.elapsed_ms, loading: false, id: result.message_ids?.assistant })
      userMessage.id = result.message_ids?.user; loadSessions()
    } catch (error) {
      pending.content = error.response?.data?.detail || error.message; pending.error = true
    } finally { pending.loading = false; sending.value = false; scrollToBottom() }
    return
  }
  await startStream(payload, event => {
    if (event.event === 'status') pending.phase = event.data.phase
    if (event.event === 'route') { pending.route = event.data.route; pending.intent = event.data.semantic_intent }
    if (event.event === 'token') { pending.phase = 'generating'; pending.content += event.data.text }
    if (event.event === 'sources') pending.sources = event.data || []
    if (event.event === 'trace') pending.trace = event.data || []
    if (event.event === 'done') {
      Object.assign(pending, { content: event.data.answer, sources: event.data.sources || [], trace: event.data.trace || [], elapsedMs: event.data.elapsed_ms, status: event.data.status, loading: false, id: event.data.message_ids?.assistant })
      userMessage.id = event.data.message_ids?.user; loadSessions()
    }
    if (event.event === 'error') { pending.content = event.data.message || '回答生成失败'; pending.error = true; pending.loading = false }
    scrollToBottom()
  })
  sending.value = false; pending.loading = false
}

function stop() { cancelStream(); sending.value = false }
function renderAnswer(markdown) {
  return renderSafeMarkdown((markdown || '').replace(/\[(\d+)\]/g, '<button class="citation-mark" data-citation="$1">$1</button>'))
}
function handleAnswerClick(event, message) {
  const button = event.target.closest?.('[data-citation]')
  if (button) openSources(message, Number(button.dataset.citation))
}
function openSources(message, number = null) {
  drawerSources.value = message.sources || []; activeCitation.value = number; drawerOpen.value = true
}
function startEdit(message) { message.editing = true; message.editBuf = message.content }
async function saveEdit(message) {
  if (!message.editBuf?.trim()) return ElMessage.warning('内容不能为空')
  if (message.id) await editMessage(message.id, message.editBuf)
  message.content = message.editBuf; message.editing = false
}
async function showMemory() {
  memoryData.value = await getSessionMemory(currentSession.value); memoryVisible.value = true
}
onMounted(async () => { await Promise.all([loadKbs(), loadSessions()]); newChat() })
</script>

<template>
  <div class="chat-layout">
    <aside class="session-panel">
      <div class="session-heading"><span class="serif">卷册</span><small>{{ sessions.length }} 则对话</small></div>
      <el-button type="primary" class="new-chat-btn" :icon="Plus" @click="newChat">新建对话</el-button>
      <div class="session-list">
        <button v-for="session in sessions" :key="session.session_id" class="session-item" :class="{ active: session.session_id === currentSession }" @click="openSession(session.session_id)">
          <span class="session-preview">{{ session.preview }}</span>
          <span class="session-meta">{{ session.message_count }} 条 · {{ session.last_at?.slice(5, 16) }}<el-icon class="session-del" @click.stop="removeSession(session.session_id)"><Delete /></el-icon></span>
        </button>
        <div v-if="!sessions.length" class="session-empty">尚无旧卷</div>
      </div>
    </aside>

    <section class="conversation-shell">
      <main class="chat-main">
        <header class="chat-toolbar">
          <div class="toolbar-group"><span class="toolbar-label">参考范围</span><el-select v-model="selectedKb" placeholder="全部知识库" clearable style="width:190px"><el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" /></el-select></div>
          <div class="route-policy"><i :class="{ off: !settings.webEnabled }"></i>{{ settings.webEnabled ? '按问题判断是否联网' : '联网已关闭' }}</div>
          <div class="toolbar-spacer"></div><el-button text :icon="Collection" @click="showMemory" v-if="settings.useMemory">会话记忆</el-button>
        </header>

        <div ref="listRef" class="msg-list">
          <div v-if="!messages.length" class="empty-state">
            <div class="empty-overline">ASK WITH CONTEXT</div><div class="empty-mark serif">问</div>
            <h2 class="serif">问有所据，答有所源</h2>
            <p>普通问题直接回答；需要资料或时效信息时，系统会自动选择合适路径。</p>
            <div class="empty-rules"><span>解释概念</span><span>查询资料</span><span>了解最新信息</span><span>协助写作</span></div>
          </div>
          <div v-for="(message, index) in messages" :key="message.id || index" class="msg-row" :class="message.role">
            <div class="avatar" :class="message.role">{{ message.role === 'user' ? '我' : '知' }}</div>
            <article class="bubble" :class="[message.role, { error: message.error }]">
              <template v-if="message.editing">
                <el-input v-model="message.editBuf" type="textarea" :rows="4" /><div class="edit-actions"><el-button size="small" @click="message.editing=false">取消</el-button><el-button size="small" type="primary" @click="saveEdit(message)">保存</el-button></div>
              </template>
              <template v-else>
                <ProcessTrace v-if="message.role === 'assistant'" :trace="message.trace || []" :elapsed-ms="message.elapsedMs" :active-phase="message.loading ? phaseLabels[message.phase] : ''" />
                <div v-if="message.role === 'user'" class="plain">{{ message.content }}</div>
                <div v-else class="md-body" :class="{ streaming: message.loading && message.content }" v-html="renderAnswer(message.content)" @click="handleAnswerClick($event, message)"></div>
                <div v-if="message.role === 'assistant' && (message.route || message.sources?.length)" class="answer-footer"><span v-if="message.route" class="route-badge">{{ routeLabels[message.route] || message.route }}</span><button v-if="message.sources?.length" class="source-trigger" @click="openSources(message)">引用 {{ message.sources.length }} 项</button></div>
                <button class="edit-button" aria-label="编辑消息" @click="startEdit(message)"><el-icon><Edit /></el-icon></button>
              </template>
            </article>
          </div>
        </div>

        <footer class="input-dock">
          <el-input v-model="input" type="textarea" :autosize="{ minRows: 1, maxRows: 5 }" resize="none" placeholder="写下你的问题…" :disabled="sending" @keydown.enter.exact.prevent="settings.enterSend && send()" />
          <el-button v-if="sending" class="send-button stop" :icon="VideoPause" @click="stop">停止</el-button><el-button v-else type="primary" class="send-button" :icon="Promotion" @click="send">发送</el-button>
          <div class="input-note">Enter 发送 · 回答可能根据问题检索知识库或网络</div>
        </footer>
      </main>
      <SourceDrawer :open="drawerOpen" :sources="drawerSources" :active-number="activeCitation" @close="drawerOpen=false" />
    </section>
    <el-dialog v-model="memoryVisible" title="会话记忆" width="520px" append-to-body><h4>对话摘要</h4><p class="memory-copy">{{ memoryData.summary || '暂无摘要' }}</p><h4>关键要点</h4><pre class="memory-copy">{{ memoryData.facts || '暂无要点' }}</pre></el-dialog>
  </div>
</template>

<style scoped>
.chat-layout{display:flex;gap:14px;height:100%;min-height:0}.session-panel{width:232px;flex:0 0 auto;display:flex;flex-direction:column;background:rgba(253,252,248,.78);border:1px solid var(--hairline);border-radius:4px 14px 14px 4px;overflow:hidden}.session-heading{padding:18px 17px 8px;display:flex;justify-content:space-between;align-items:baseline}.session-heading span{font-size:17px;font-weight:700;letter-spacing:.16em}.session-heading small{color:var(--ink-3)}.new-chat-btn{margin:7px 13px 13px;height:38px;letter-spacing:.12em}.session-list{overflow:auto;padding:0 9px 12px}.session-item{width:100%;text-align:left;border:0;border-left:2px solid transparent;background:transparent;padding:11px 12px;cursor:pointer;color:inherit;border-radius:2px 9px 9px 2px}.session-item:hover{background:var(--paper-3)}.session-item.active{background:var(--accent-wash);border-left-color:var(--accent)}.session-preview{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px}.session-meta{display:flex;justify-content:space-between;margin-top:5px;color:var(--ink-3);font-size:10px}.session-del:hover{color:var(--seal)}.session-empty{text-align:center;color:var(--ink-3);padding:40px 0;font-size:12px}
.conversation-shell{flex:1;min-width:0;display:flex;overflow:hidden;background:var(--paper-2);border:1px solid var(--hairline);border-radius:14px 4px 4px 14px;box-shadow:var(--el-box-shadow-light)}.chat-main{flex:1;min-width:0;display:flex;flex-direction:column}.chat-toolbar{height:64px;flex:0 0 auto;display:flex;align-items:center;gap:20px;padding:0 20px;border-bottom:1px solid var(--hairline-soft)}.toolbar-group{display:flex;align-items:center;gap:9px}.toolbar-label{font-size:11px;color:var(--ink-3);letter-spacing:.12em}.toolbar-spacer{flex:1}.route-policy{font-size:12px;color:var(--ink-2);display:flex;align-items:center;gap:7px;white-space:nowrap}.route-policy i{width:7px;height:7px;border-radius:50%;background:#5e8a5c;box-shadow:0 0 0 4px rgba(94,138,92,.1)}.route-policy i.off{background:var(--ink-3);box-shadow:none}
.msg-list{flex:1;overflow:auto;padding:26px clamp(18px,4vw,58px) 18px}.empty-state{height:100%;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;animation:rise .6s ease both}.empty-overline{font:10px/1 Georgia,serif;letter-spacing:.26em;color:var(--seal)}.empty-mark{width:82px;height:82px;display:grid;place-items:center;margin:18px 0;border:1px solid rgba(176,74,50,.34);color:var(--seal);font-size:45px;transform:rotate(-2deg);background:rgba(176,74,50,.025)}.empty-state h2{font-size:22px;letter-spacing:.14em}.empty-state p{max-width:530px;color:var(--ink-2);line-height:1.8;margin-top:9px;font-size:13px}.empty-rules{display:flex;gap:8px;margin-top:24px}.empty-rules span{padding:6px 12px;border-top:1px solid var(--hairline);border-bottom:1px solid var(--hairline);color:var(--ink-2);font-size:11px}
.msg-row{display:flex;gap:11px;margin-bottom:22px;animation:rise .28s ease both}.msg-row.user{flex-direction:row-reverse}.avatar{width:32px;height:32px;display:grid;place-items:center;border-radius:50%;flex:0 0 auto;font:600 12px "Noto Serif SC","Songti SC",serif}.avatar.user{background:var(--accent-wash);color:var(--accent-deep)}.avatar.assistant{background:var(--seal);color:white;border-radius:5px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.35)}.bubble{position:relative;max-width:min(780px,82%);padding:13px 16px;border:1px solid var(--hairline);background:#fffefa;border-radius:4px 13px 13px 13px}.bubble.user{background:var(--accent-wash);border-color:rgba(62,111,104,.16);border-radius:13px 4px 13px 13px}.bubble.error{border-color:rgba(176,74,50,.35)}.plain{white-space:pre-wrap;line-height:1.7}.streaming::after{content:"";display:inline-block;width:2px;height:1em;margin-left:3px;vertical-align:-2px;background:var(--seal);animation:blink .8s steps(1) infinite}@keyframes blink{50%{opacity:0}}
.answer-footer{display:flex;gap:12px;align-items:center;margin-top:12px;padding-top:9px;border-top:1px solid var(--hairline-soft)}.route-badge{font-size:10px;letter-spacing:.08em;color:var(--ink-3)}.source-trigger{border:0;background:transparent;color:var(--accent-deep);font-size:12px;cursor:pointer;border-bottom:1px solid rgba(46,86,79,.28)}.edit-button{position:absolute;right:-8px;top:-9px;opacity:0;border:1px solid var(--hairline);background:var(--paper-2);color:var(--ink-3);border-radius:5px;cursor:pointer}.bubble:hover .edit-button{opacity:1}.edit-actions{text-align:right;margin-top:8px}.md-body :deep(.citation-mark){display:inline-grid;place-items:center;min-width:18px;height:18px;margin:0 2px;padding:0 4px;border:0;border-radius:9px;background:var(--accent-wash);color:var(--accent-deep);font:700 10px Georgia,serif;cursor:pointer;vertical-align:2px}.md-body :deep(.citation-mark:hover){background:var(--accent);color:white}
.input-dock{position:relative;display:flex;gap:10px;padding:14px 18px 30px;border-top:1px solid var(--hairline-soft);background:rgba(253,252,248,.92)}.input-dock :deep(.el-textarea__inner){min-height:43px!important;padding:11px 14px;border-radius:10px;background:var(--paper);box-shadow:0 0 0 1px var(--hairline) inset}.send-button{width:92px;height:43px}.send-button.stop{color:var(--seal);border-color:rgba(176,74,50,.3)}.input-note{position:absolute;left:20px;bottom:7px;color:var(--ink-3);font-size:9px;letter-spacing:.03em}.memory-copy{white-space:pre-wrap;font:13px/1.8 var(--el-font-family);color:var(--ink-2);margin:7px 0 18px}
@media (max-width:1100px){.session-panel{width:190px}.route-policy{display:none}.chat-toolbar{padding:0 12px}.toolbar-label{display:none}.empty-rules{display:none}.empty-state{padding:20px}.msg-list{padding-left:16px;padding-right:16px}}
</style>
