<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Edit, Collection } from '@element-plus/icons-vue'
import { renderSafeMarkdown } from '../security'
import { listKbs, chat, listSessions, getSessionMessages, deleteSession, editMessage, getSessionMemory } from '../api'
import { settings } from '../settings'

const kbs = ref([])
const sessions = ref([])
const currentSession = ref('')
const selectedKb = ref(null)
const input = ref('')
const sending = ref(false)
const messages = ref([])       // {id, role, content, intent?, trace?, sources?, loading?, editing?, editBuf?}
const listRef = ref(null)
const memoryVisible = ref(false)
const memoryData = ref({ summary: '', facts: '' })

const INTENT_LABELS = {
  kb: { text: '知识库回答', type: 'success' },
  web: { text: '联网搜索', type: 'warning' },
  chitchat: { text: '闲聊', type: 'info' },
}

const STAGE_LABELS = {
  understand: '意图识别与查询理解',
  chitchat: '闲聊直达',
  retrieve: '向量召回（粗筛）',
  rerank: '重排序（精排）',
  rewrite: '查询改写重试',
  web_search: '联网搜索',
  generate: '组织回答',
}

function newSessionId() {
  return 's' + Date.now().toString(36)
}

async function loadKbs() {
  kbs.value = await listKbs()
}

async function loadSessions() {
  sessions.value = await listSessions()
}

async function openSession(sid) {
  currentSession.value = sid
  const msgs = await getSessionMessages(sid)
  messages.value = msgs.map(m => ({ id: m.id, role: m.role, content: m.content }))
  scrollToBottom()
}

async function newChat() {
  currentSession.value = newSessionId()
  messages.value = []
}

async function removeSession(sid) {
  await ElMessageBox.confirm('删除该会话的全部历史记录？', '删除确认', { type: 'warning' })
  await deleteSession(sid)
  ElMessage.success('已删除')
  if (currentSession.value === sid) newChat()
  loadSessions()
}

async function send() {
  const q = input.value.trim()
  if (!q || sending.value) return
  if (!currentSession.value) currentSession.value = newSessionId()
  input.value = ''
  const userMessage = { role: 'user', content: q }
  messages.value.push(userMessage)
  const pending = { role: 'assistant', content: '', sources: null, loading: true }
  messages.value.push(pending)
  scrollToBottom()
  sending.value = true
  try {
    const res = await chat(q, currentSession.value, {
      kbId: selectedKb.value,
      topK: settings.topK,
      webEnabled: settings.webEnabled,
      simThreshold: settings.simThreshold,
      useMemory: settings.useMemory,
    })
    pending.content = res.answer
    pending.sources = res.sources
    pending.intent = res.intent
    pending.trace = res.trace || []
    pending.elapsedMs = res.elapsed_ms
    userMessage.id = res.message_ids?.user
    pending.id = res.message_ids?.assistant
    loadSessions()   // 刷新侧栏预览与排序
  } catch (e) {
    pending.content = '请求失败：' + (e.response?.data?.detail || e.message)
  } finally {
    pending.loading = false
    sending.value = false
    scrollToBottom()
  }
}

// ---------- 会话记忆 ----------
async function showMemory() {
  if (!currentSession.value) return ElMessage.warning('当前是新会话，还没有记忆')
  try {
    memoryData.value = await getSessionMemory(currentSession.value)
    memoryVisible.value = true
  } catch (e) {
    ElMessage.error('获取记忆失败：' + (e.response?.data?.detail || e.message))
  }
}

// ---------- 消息编辑 ----------
function startEdit(m) {
  m.editing = true
  m.editBuf = m.content
}
function cancelEdit(m) {
  m.editing = false
}
async function saveEdit(m) {
  if (!m.editBuf?.trim()) return ElMessage.warning('内容不能为空')
  if (m.id) {
    await editMessage(m.id, m.editBuf)
    ElMessage.success('已保存')
  }
  m.content = m.editBuf
  m.editing = false
}

function render(md) {
  return renderSafeMarkdown(md)
}

function scrollToBottom() {
  nextTick(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

onMounted(async () => {
  await loadKbs()
  await loadSessions()
  newChat()
})
</script>

<template>
  <div class="chat-layout">
    <!-- 会话侧栏 -->
    <div class="session-panel">
      <el-button type="primary" class="new-chat-btn" :icon="Plus" @click="newChat">新建对话</el-button>
      <div class="session-list">
        <div v-for="s in sessions" :key="s.session_id"
             class="session-item" :class="{ active: s.session_id === currentSession }"
             @click="openSession(s.session_id)">
          <div class="session-preview">{{ s.preview }}</div>
          <div class="session-meta">
            <span>{{ s.message_count }} 条 · {{ s.last_at?.slice(5, 16) }}</span>
            <el-icon class="session-del" @click.stop="removeSession(s.session_id)"><Delete /></el-icon>
          </div>
        </div>
        <el-empty v-if="!sessions.length" description="暂无历史会话" :image-size="60" />
      </div>
    </div>

    <!-- 对话区 -->
    <div class="chat-main">
      <div class="chat-toolbar">
        <el-select v-model="selectedKb" placeholder="检索全部向量库" clearable style="width: 200px" size="default">
          <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
        <el-tag v-if="settings.webEnabled" type="success" size="small" effect="plain">联网兜底</el-tag>
        <el-tag v-else type="info" size="small" effect="plain">联网关闭</el-tag>
        <el-tag v-if="settings.useMemory" type="success" size="small" effect="plain">长期记忆</el-tag>
        <span class="toolbar-tip">top_k={{ settings.topK }} · 阈值={{ settings.simThreshold }}</span>
        <div style="flex:1"></div>
        <el-button size="small" :icon="Collection" @click="showMemory" v-if="settings.useMemory">会话记忆</el-button>
      </div>

      <div ref="listRef" class="msg-list">
        <div v-if="!messages.length" class="empty-state">
          <div class="empty-mark serif">问</div>
          <div class="empty-title serif">有所问，必有所答</div>
          <div class="empty-sub">知识库优先作答，资料不足自动联网补充</div>
          <div class="empty-hints">
            <span class="hint-chip">语义检索</span>
            <span class="hint-chip">意图路由</span>
            <span class="hint-chip">多轮记忆</span>
            <span class="hint-chip">联网补充</span>
          </div>
        </div>
        <div v-for="(m, i) in messages" :key="i" class="msg-row" :class="m.role">
          <div class="avatar" :class="m.role">{{ m.role === 'user' ? '我' : '知' }}</div>
          <div class="bubble" :class="m.role">
            <div v-if="m.loading" class="loading-row">
              <el-icon class="is-loading" style="font-size: 16px"><i class="el-icon-loading" /></el-icon>
              检索知识库 · 生成回答中，可能需要数十秒…
            </div>
            <template v-else-if="m.editing">
              <el-input v-model="m.editBuf" type="textarea" :rows="4" />
              <div class="edit-actions">
                <el-button size="small" @click="cancelEdit(m)">取消</el-button>
                <el-button size="small" type="primary" @click="saveEdit(m)">保存</el-button>
              </div>
            </template>
            <template v-else>
              <!-- AI 思维链（默认折叠，可展开） -->
              <el-collapse v-if="m.trace && m.trace.length" class="trace-collapse">
                <el-collapse-item name="trace">
                  <template #title>
                    <span class="trace-title">
                      AI 思维链（{{ m.trace.length }} 步<span v-if="m.elapsedMs"> · 总耗时 {{ (m.elapsedMs / 1000).toFixed(1) }}s</span>）
                    </span>
                  </template>
                  <div class="trace-body">
                    <div v-for="(t, j) in m.trace" :key="j" class="trace-step">
                      <div class="trace-step-head">
                        <span class="trace-no">{{ j + 1 }}</span>
                        <span class="trace-stage">{{ STAGE_LABELS[t.stage] || t.stage }}</span>
                        <span v-if="t.ms != null" class="trace-ms">{{ t.ms >= 1000 ? (t.ms / 1000).toFixed(1) + 's' : t.ms + 'ms' }}</span>
                      </div>
                      <div class="trace-detail">
                        <template v-if="t.stage === 'understand'">
                          <div v-if="t.reason" class="trace-reason">判定理由：{{ t.reason }}</div>
                          <div>
                            意图：<b>{{ INTENT_LABELS[t.intent]?.text || t.intent }}</b>
                            <span v-if="t.route" class="trace-route">→ {{ t.route }}</span>；
                            检索 query：<b>{{ t.query }}</b><span v-if="t.rewritten">（已消解指代/改写）</span>
                          </div>
                        </template>
                        <template v-else-if="t.stage === 'retrieve'">
                          <div>向量召回 {{ t.candidates?.length || 0 }} 条候选，过阈值（{{ t.threshold }}）{{ t.passed }} 条：</div>
                          <div v-for="(c, k) in t.candidates" :key="k" class="trace-line"
                               :class="{ fail: c.sim < t.threshold }">
                            相似度 {{ c.sim }} ｜ {{ c.text }}…
                          </div>
                        </template>
                        <template v-else-if="t.stage === 'rerank'">
                          <div v-if="t.note">{{ t.note }}，转入下一步兜底</div>
                          <div v-else-if="t.mode">{{ t.mode }}，保留 {{ t.kept }} 条</div>
                          <template v-else>
                            <div>交叉编码器精排（阈值 {{ 0.3 }}），保留 {{ t.kept }} 条：</div>
                            <div v-for="(c, k) in t.scores" :key="k" class="trace-line"
                                 :class="{ fail: c.score < 0.3 }">
                              相关性 {{ c.score }} ｜ {{ c.text }}…
                            </div>
                          </template>
                        </template>
                        <template v-else-if="t.stage === 'rewrite'">
                          检索不足，改写为：「{{ t.query }}」后重试
                        </template>
                        <template v-else-if="t.stage === 'web_search'">
                          <div>{{ t.note || '联网搜索' }}「{{ t.query }}」，获得 {{ t.results?.length || 0 }} 条结果：</div>
                          <div v-for="(r, k) in (t.results || []).slice(0, 3)" :key="k" class="trace-line">
                            · <a :href="r.url" target="_blank" class="src-web">{{ r.title || r.url }}</a>
                          </div>
                        </template>
                        <template v-else-if="t.stage === 'generate'">
                          基于知识库片段 {{ t.kb_docs }} 条、网络资料 {{ t.web_docs }} 条组织回答<span v-if="t.memory_used">（已注入长期记忆）</span>
                        </template>
                        <template v-else-if="t.stage === 'chitchat'">
                          {{ t.note || '直接回答，不检索' }}
                        </template>
                        <template v-else>{{ t.stage }}</template>
                      </div>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>

              <div v-if="m.role === 'user'" class="plain">{{ m.content }}</div>
              <template v-else>
                <div class="md-body" v-html="render(m.content)"></div>
                <el-tag v-if="m.intent && INTENT_LABELS[m.intent]" :type="INTENT_LABELS[m.intent].type"
                        size="small" effect="light" style="margin-top: 6px">
                  {{ INTENT_LABELS[m.intent].text }}
                </el-tag>
              </template>
              <div class="msg-actions">
                <el-icon class="act" title="编辑" @click="startEdit(m)"><Edit /></el-icon>
              </div>
              <el-collapse v-if="m.sources && (m.sources.kb.length || m.sources.web.length)" class="src-collapse">
                <el-collapse-item :title="`引用来源（知识库 ${m.sources.kb.length} · 网络 ${m.sources.web.length}）`" name="src">
                  <div v-if="m.sources.kb.length" style="margin-bottom: 6px">
                    <div v-for="(k, j) in m.sources.kb" :key="'k' + j" class="src-kb">
                      {{ k.slice(0, 120) }}{{ k.length > 120 ? '…' : '' }}
                    </div>
                  </div>
                  <div v-if="m.sources.web.length">
                    <div v-for="(w, j) in m.sources.web" :key="'w' + j">
                      <a :href="w.url" target="_blank" class="src-web">{{ w.title || w.url }}</a>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </template>
          </div>
        </div>
      </div>

      <div class="input-bar">
        <el-input v-model="input" placeholder="问之所问 —— 输入问题，Enter 发送" :disabled="sending"
                  @keyup.enter="settings.enterSend && send()" size="large" />
        <el-button type="primary" size="large" :loading="sending" @click="send" style="width: 96px">发送</el-button>
      </div>
    </div>

    <el-dialog v-model="memoryVisible" title="会话长期记忆" width="520px" append-to-body>
      <div v-if="memoryData.summary || memoryData.facts">
        <h4 style="margin: 0 0 6px">对话摘要</h4>
        <p style="color: #606266; font-size: 13px; line-height: 1.7">{{ memoryData.summary || '（暂无）' }}</p>
        <h4 style="margin: 12px 0 6px">关键要点</h4>
        <pre style="white-space: pre-wrap; color: #606266; font-size: 13px; font-family: inherit; line-height: 1.8">{{ memoryData.facts || '（暂无）' }}</pre>
      </div>
      <el-empty v-else description="当前会话还没有形成记忆，多聊几轮后自动归纳" :image-size="70" />
    </el-dialog>
  </div>
</template>

<style scoped>
.chat-layout { display: flex; gap: 14px; height: 100%; min-height: 0; }

/* —— 会话侧栏：卷目 —— */
.session-panel {
  width: 248px; flex-shrink: 0; background: var(--paper-2); border-radius: 14px;
  border: 1px solid var(--hairline); display: flex; flex-direction: column;
  overflow: hidden; box-shadow: var(--el-box-shadow-light);
}
.new-chat-btn { margin: 14px 14px 10px; height: 38px; font-weight: 500; letter-spacing: 0.12em; }
.session-list { flex: 1; overflow: auto; padding: 0 10px 10px; }
.session-item {
  padding: 11px 13px; border-radius: 10px; cursor: pointer; margin-bottom: 4px;
  border: 1px solid transparent; transition: background 0.16s ease, border-color 0.16s ease;
}
.session-item:hover { background: var(--paper-3); }
.session-item.active {
  background: var(--accent-wash);
  border-color: rgba(62, 111, 104, 0.22);
}
.session-preview {
  font-size: 13px; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.session-meta {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 11px; color: var(--ink-3); margin-top: 5px;
}
.session-del { visibility: hidden; cursor: pointer; }
.session-del:hover { color: var(--seal); }
.session-item:hover .session-del { visibility: visible; }

/* —— 对话主区 —— */
.chat-main {
  flex: 1; background: var(--paper-2); border-radius: 14px; border: 1px solid var(--hairline);
  display: flex; flex-direction: column; min-width: 0;
  box-shadow: var(--el-box-shadow-light);
}
.chat-toolbar {
  display: flex; align-items: center; gap: 10px; padding: 13px 20px;
  border-bottom: 1px solid var(--hairline-soft);
}
.toolbar-tip { font-size: 12px; color: var(--ink-3); letter-spacing: 0.03em; }
.msg-list { flex: 1; overflow: auto; padding: 22px 22px 12px; }

/* —— 空状态：大字问 —— */
.empty-state {
  height: 100%; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px;
  animation: rise 0.6s ease both;
}
.empty-mark {
  width: 92px; height: 92px; display: flex; align-items: center; justify-content: center;
  font-size: 52px; font-weight: 600; color: var(--accent);
  background: var(--accent-wash); border-radius: 26px;
  box-shadow: inset 0 0 0 1px rgba(62, 111, 104, 0.14);
  animation: seal-press 0.7s cubic-bezier(0.2, 1.4, 0.4, 1) both;
}
.empty-title { font-size: 19px; font-weight: 600; color: var(--ink); letter-spacing: 0.14em; margin-top: 6px; }
.empty-sub { font-size: 13px; color: var(--ink-2); letter-spacing: 0.05em; }
.empty-hints { display: flex; gap: 8px; margin-top: 14px; }
.hint-chip {
  font-size: 12px; color: var(--ink-2); padding: 4px 13px;
  border: 1px solid var(--hairline); border-radius: 999px; background: var(--paper-2);
  letter-spacing: 0.06em;
}

/* —— 消息 —— */
.msg-row { display: flex; gap: 11px; margin-bottom: 18px; animation: rise 0.32s ease both; }
.msg-row.user { flex-direction: row-reverse; }
.avatar {
  width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 600;
  font-family: "Noto Serif SC", "Songti SC", SimSun, serif;
}
.avatar.user {
  background: var(--accent-wash); color: var(--accent-deep);
  box-shadow: inset 0 0 0 1px rgba(62, 111, 104, 0.25);
}
.avatar.assistant {
  border-radius: 9px; background: var(--seal); color: #fdfcf8;
  box-shadow: inset 0 0 0 1.5px rgba(255, 255, 255, 0.25), 0 2px 5px rgba(176, 74, 50, 0.25);
}
.bubble {
  max-width: 76%; padding: 11px 15px; border-radius: 13px; position: relative;
}
.bubble.user {
  background: var(--accent-wash); color: #23453f;
  border: 1px solid rgba(62, 111, 104, 0.16);
  border-top-right-radius: 4px;
}
.bubble.assistant {
  background: #fffdf9; color: var(--ink);
  border: 1px solid var(--hairline);
  border-top-left-radius: 4px;
  box-shadow: 0 1px 2px rgba(60, 52, 32, 0.04);
}
.plain { white-space: pre-wrap; }
.loading-row { display: flex; align-items: center; gap: 9px; color: var(--ink-3); font-size: 13px; letter-spacing: 0.04em; }
.msg-actions { position: absolute; top: -11px; right: -7px; visibility: hidden; }
.bubble:hover .msg-actions { visibility: visible; }
.act {
  background: var(--paper-2); border: 1px solid var(--hairline); border-radius: 5px;
  padding: 2px; cursor: pointer; font-size: 12px; color: var(--ink-2);
}
.act:hover { color: var(--accent-deep); border-color: var(--accent); }
.edit-actions { margin-top: 8px; text-align: right; }

/* —— AI 思维链：眉批 —— */
.trace-collapse { margin-bottom: 7px; }
.trace-collapse :deep(.el-collapse-item__header) {
  font-size: 12px; color: var(--accent-deep); height: 30px; line-height: 30px;
  background: transparent; border-bottom: none; letter-spacing: 0.05em;
}
.trace-collapse :deep(.el-collapse-item__wrap) { background: transparent; }
.trace-collapse :deep(.el-collapse-item__content) { padding-bottom: 6px; }
.trace-title { font-weight: 600; }
.trace-body {
  border-left: 2px solid rgba(62, 111, 104, 0.28);
  padding-left: 12px; background: rgba(62, 111, 104, 0.03);
  border-radius: 0 6px 6px 0; padding-top: 4px; padding-bottom: 4px;
}
.trace-step { margin-bottom: 9px; }
.trace-step-head { display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }
.trace-no {
  width: 16px; height: 16px; border-radius: 50%; background: var(--accent); color: #fff;
  font-size: 10px; display: flex; align-items: center; justify-content: center;
}
.trace-stage { font-size: 12px; font-weight: 600; color: var(--ink); letter-spacing: 0.03em; }
.trace-ms {
  font-size: 11px; color: var(--ink-3); background: var(--paper-3);
  border-radius: 8px; padding: 0 7px;
  font-variant-numeric: tabular-nums;
}
.trace-reason { color: var(--accent-deep); margin-bottom: 2px; }
.trace-route { color: #4e7d4a; font-weight: 600; }
.trace-detail { font-size: 12px; color: var(--ink-2); line-height: 1.75; }
.trace-line { padding: 1.5px 0; font-variant-numeric: tabular-nums; }
.trace-line.fail { color: #bab4a6; text-decoration: line-through; }

/* —— 引用来源 —— */
.src-collapse { margin-top: 9px; border-top: 1px dashed var(--hairline); }
.src-collapse :deep(.el-collapse-item__header) { font-size: 12px; color: var(--ink-3); height: 32px; line-height: 32px; }
.src-kb {
  font-size: 12px; color: var(--ink-2); background: var(--paper); padding: 6px 10px;
  margin-top: 5px; border-radius: 6px; border: 1px solid var(--hairline-soft);
  line-height: 1.6;
}
.src-web { font-size: 13px; color: var(--accent); text-decoration: none; }
.src-web:hover { text-decoration: underline; text-underline-offset: 3px; }

/* —— 输入区 —— */
.input-bar {
  display: flex; gap: 11px; padding: 14px 18px 16px; border-top: 1px solid var(--hairline-soft);
}
.input-bar :deep(.el-input__wrapper) {
  background: var(--paper); border-radius: 11px;
  box-shadow: 0 0 0 1px var(--hairline) inset;
  padding: 4px 15px;
  transition: box-shadow 0.2s ease;
}
.input-bar :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--accent) inset, 0 0 0 3px rgba(62, 111, 104, 0.1);
}
.input-bar :deep(.el-input__inner) { color: var(--ink); }
.input-bar :deep(.el-input__inner::placeholder) { color: var(--ink-3); letter-spacing: 0.03em; }
</style>
