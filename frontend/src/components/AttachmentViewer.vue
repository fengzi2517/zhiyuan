<script setup>
import { ref, watch } from 'vue'
import { getAttachmentContent, getAttachmentUrl } from '../api'
const props = defineProps({ source: Object, sessionId: String })
const content = ref(''), error = ref(''), loading = ref(false)
let version = 0
watch(() => [props.source, props.sessionId], async () => {
  const v = ++version
  content.value = ''; error.value = ''; loading.value = true
  try { const result = await getAttachmentContent(props.source.session_id || props.sessionId, props.source.attachment_id); if (v === version) content.value = result.content || '这张图片没有可提取文字，请查看原图。' }
  catch { if (v === version) error.value = '附件不可访问或已删除' }
  finally { if (v === version) loading.value = false }
}, { immediate: true })
</script>
<template><div><a :href="getAttachmentUrl(source.session_id || sessionId, source.attachment_id)" target="_blank" rel="noopener noreferrer">打开附件原文件 ↗</a><p v-if="source.location">引用位置：{{ source.location }}</p><blockquote v-if="source.content">{{ source.content }}</blockquote><p v-if="loading">正在加载原文…</p><p v-else-if="error" role="alert">{{ error }}</p><pre v-else>{{ content }}</pre></div></template>
<style scoped>pre{white-space:pre-wrap;line-height:1.8;max-height:65vh;overflow:auto;font-family:inherit}a{color:var(--accent-deep)}blockquote{padding:12px;border-left:3px solid var(--accent);background:var(--accent-wash);margin:15px 0}</style>
