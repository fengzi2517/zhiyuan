<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { listAttachments, uploadAttachments, retryAttachment, removeAttachment, saveAttachment, getAttachmentUrl, getAttachmentPreviewUrl } from '../api'
import { validateFiles, attachmentBlocker } from '../attachments'
const props = defineProps({ sessionId: String, vision: Boolean, disabled: Boolean, kbs: Array })
const emit = defineEmits(['change', 'uploaded'])
const cards = ref([]), ids = ref([]), uploading = ref(false), picker = ref(null), error = ref('')
const saveCard = ref(null), targetKb = ref(null), saving = ref(false)
const editableKbs = computed(() => (props.kbs || []).filter(k => ['owner', 'editor'].includes(k.role)))
const chosen = computed(() => cards.value.filter(c => ids.value.includes(c.id)))
const blocker = computed(() => uploading.value ? '附件正在上传' : attachmentBlocker(chosen.value, props.vision))
const labels = { queued: '等待处理', running: '正在解析', retry_wait: '等待重试', ready: '已就绪', failed: '处理失败' }
let timer, version = 0, listVersion = 0
watch([chosen, blocker], () => emit('change', { cards: chosen.value, blocked: !!blocker.value }), { immediate: true })
function schedule(v) {
  clearTimeout(timer)
  if (cards.value.some(c => ['queued', 'running', 'retry_wait'].includes(c.status))) timer = setTimeout(() => refresh(v), 2000)
}
async function refresh(v = version) {
  const sid = props.sessionId
  if (!sid) return
  const request = ++listVersion
  try { const rows = await listAttachments(sid); if (v !== version || request !== listVersion) return; cards.value = rows; error.value = ''; schedule(v) }
  catch (e) { if (v === version && request === listVersion) { error.value = '附件状态加载失败，请刷新重试'; clearTimeout(timer) } }
}
watch(() => props.sessionId, () => { version++; clearTimeout(timer); cards.value = []; ids.value = []; uploading.value = false; error.value = ''; saveCard.value = null; refresh(version) }, { immediate: true })
onUnmounted(() => { version++; clearTimeout(timer) })
async function addFiles(files) {
  if (props.disabled || uploading.value || !files.length) return
  const problem = validateFiles(files, chosen.value)
  if (problem) return ElMessage.warning(problem)
  const v = version, sid = props.sessionId
  uploading.value = true
  try {
    const rows = await uploadAttachments(sid, files)
    if (v !== version) return
    listVersion++
    // A concurrent GET may already contain the committed upload before POST returns.
    cards.value = [...new Map([...rows, ...cards.value].map(card => [card.id, card])).values()]
    ids.value = [...new Set([...ids.value, ...rows.map(card => card.id)])]
    schedule(v); emit('uploaded')
  }
  catch (e) { if (v === version) ElMessage.error(e.response?.data?.detail || '附件上传失败') }
  finally { if (v === version) uploading.value = false }
}
function paste(event) { const files = Array.from(event.clipboardData?.files || []); if (files.length) { event.preventDefault(); addFiles(files) } }
function toggle(card, checked) { if (!checked) ids.value = ids.value.filter(id => id !== card.id); else { const problem = validateFiles([], [...chosen.value, card]); if (problem) return ElMessage.warning(problem); ids.value.push(card.id) } }
async function action(card, retry) {
  const v = version
  try { await (retry ? retryAttachment : removeAttachment)(props.sessionId, card.id); if (v !== version) return; listVersion++; if (!retry) ids.value = ids.value.filter(id => id !== card.id); await refresh(v); emit('uploaded') }
  catch (e) { ElMessage.error(e.response?.data?.detail || '附件操作失败') }
}
async function confirmSave() {
  if (!targetKb.value) return
  const v = version
  saving.value = true
  try { await saveAttachment(props.sessionId, saveCard.value.id, targetKb.value); ElMessage.success('已提交知识库入库队列'); if (v === version) saveCard.value = null }
  catch (e) { ElMessage.error(e.response?.data?.detail || '保存失败') }
  finally { saving.value = false }
}
defineExpose({ addFiles, paste, refresh })
</script>
<template>
  <section class="attachment-composer" @dragover.prevent @drop.stop.prevent="addFiles(Array.from($event.dataTransfer.files))" @paste.stop="paste">
    <div class="attachment-heading"><button type="button" :disabled="disabled || uploading" @click="picker.click()">＋ 添加附件</button><span>仅当前会话 · 本轮选中 {{ chosen.length }}/5 项 · 可拖入或粘贴图片</span></div>
    <input ref="picker" class="file-picker" type="file" multiple accept=".png,.jpg,.jpeg,.webp,.bmp,.txt,.md,.pdf,.docx" @change="addFiles(Array.from($event.target.files)); $event.target.value = ''" />
    <div v-if="cards.length" class="attachment-cards">
      <article v-for="card in cards" :key="card.id" class="attachment-card" :class="{ chosen: ids.includes(card.id) }">
        <el-checkbox :model-value="ids.includes(card.id)" :disabled="disabled || uploading" :aria-label="`本轮使用 ${card.filename}`" @change="toggle(card, $event)" />
        <a :href="getAttachmentUrl(sessionId, card.id)" target="_blank" rel="noopener noreferrer"><img v-if="card.is_image && card.status === 'ready'" :src="getAttachmentPreviewUrl(sessionId, card.id)" :alt="card.filename" /><span v-else class="file-symbol">文</span></a>
        <div class="attachment-details"><a :href="getAttachmentUrl(sessionId, card.id)" target="_blank" rel="noopener noreferrer">{{ card.filename }}</a><small>{{ labels[card.status] || card.status }} · {{ Math.ceil(card.size / 1024) }} KB<span v-if="card.is_image && card.status === 'ready'"> · {{ vision ? '原生看图' : '文字识别' }}</span></small><small v-if="card.error" class="attachment-error">{{ card.error }}</small>
          <div class="attachment-actions"><button v-if="card.status === 'failed'" :disabled="disabled" @click="action(card, true)">重试</button><button :disabled="disabled" @click="action(card, false)">移除</button><button v-if="card.status === 'ready' && editableKbs.length" :disabled="disabled" @click="saveCard = card; targetKb = null">保存到知识库…</button></div>
        </div>
      </article>
    </div>
    <p v-if="blocker" class="attachment-error" role="status">{{ blocker }}</p>
    <p v-if="error" class="attachment-error">{{ error }} <button @click="refresh()">刷新</button></p>
    <el-dialog :model-value="!!saveCard" title="保存附件到知识库" width="440px" append-to-body @close="saveCard = null"><p>将「{{ saveCard?.filename }}」复制入库，目标知识库的成员将可检索该文档。会话删除后，知识库副本仍会保留。</p><el-select v-model="targetKb" placeholder="选择有编辑权限的知识库"><el-option v-for="kb in editableKbs" :key="kb.id" :label="kb.name" :value="kb.id" /></el-select><template #footer><el-button @click="saveCard = null">取消</el-button><el-button type="primary" :disabled="!targetKb" :loading="saving" @click="confirmSave">确认保存到所选知识库</el-button></template></el-dialog>
  </section>
</template>
<style scoped>
.attachment-composer{width:100%;font-size:12px;color:var(--ink-2)}.attachment-heading{display:flex;gap:12px;align-items:center;margin-bottom:7px}.attachment-heading span{font-size:10px;color:var(--ink-3)}button{color:var(--accent-deep);border:0;background:transparent;cursor:pointer;padding:2px}button:disabled{opacity:.45;cursor:default}.file-picker{display:none}.attachment-cards{display:flex;gap:7px;overflow:auto;max-height:155px}.attachment-card{display:flex;align-items:flex-start;gap:7px;min-width:220px;max-width:300px;border:1px solid var(--hairline);border-radius:5px;padding:8px;background:var(--paper)}.attachment-card.chosen{border-color:var(--accent);background:var(--accent-wash)}img,.file-symbol{width:36px;height:42px;object-fit:cover;display:grid;place-items:center;font-family:serif;font-size:22px}.attachment-details{min-width:0}.attachment-details a{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink);max-width:200px}.attachment-details small{display:block;font-size:10px;margin-top:3px}.attachment-actions{display:flex;gap:8px;font-size:10px}.attachment-error{color:var(--seal);margin:5px 0}.attachment-composer :deep(.el-select){margin-top:15px;width:100%}
</style>
