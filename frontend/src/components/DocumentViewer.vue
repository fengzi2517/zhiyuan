<script setup>
import { computed, onMounted, ref } from 'vue'
import { getChunkContext, getOriginalDocumentUrl } from '../api'

const props = defineProps({ source: { type: Object, required: true } })
const context = ref(null)
const error = ref('')
const isPdf = computed(() => props.source.title?.toLowerCase().endsWith('.pdf'))
const originalUrl = computed(() => `${getOriginalDocumentUrl(props.source.document_id)}${props.source.page_start ? `#page=${props.source.page_start}` : ''}`)

onMounted(async () => {
  try { context.value = await getChunkContext(props.source.document_id, props.source.chunk_id) }
  catch (e) { error.value = e.response?.data?.detail || e.message }
})
</script>

<template>
  <div class="viewer-shell">
    <iframe v-if="isPdf && !error" :src="originalUrl" :title="source.title" />
    <div v-else class="text-viewer">
      <div v-if="error" class="viewer-error">{{ error }}</div>
      <template v-else-if="context">
        <div class="viewer-location">{{ source.location || context.chunk.section }}</div>
        <pre>{{ context.chunk.content }}</pre>
      </template>
      <div v-else class="viewer-loading">正在打开原文位置…</div>
    </div>
  </div>
</template>

<style scoped>
.viewer-shell,.viewer-shell iframe { width:100%; height:100%; min-height:420px; border:0; }
.text-viewer { padding:18px; background:var(--paper); min-height:420px; }
.viewer-location { color:var(--seal); font:600 12px/1.4 var(--el-font-family); letter-spacing:.08em; margin-bottom:12px; }
pre { white-space:pre-wrap; font:14px/1.9 "Noto Serif SC","Songti SC",serif; color:var(--ink); }
.viewer-error,.viewer-loading { color:var(--ink-3); padding:24px 0; text-align:center; }
</style>
