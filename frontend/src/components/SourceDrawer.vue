<script setup>
import { computed, ref } from 'vue'
import { Close, Link } from '@element-plus/icons-vue'
import DocumentViewer from './DocumentViewer.vue'
import { dedupeSources, externalLinkAttrs } from './source-utils'

const props = defineProps({ sources: { type: Array, default: () => [] }, open: Boolean, activeNumber: Number })
const emit = defineEmits(['close'])
const selected = ref(null)
const items = computed(() => dedupeSources(props.sources))
const attrs = externalLinkAttrs()
</script>

<template>
  <aside class="source-drawer" :class="{ open }" aria-label="引用资料">
    <header>
      <div><span class="eyebrow">REFERENCES</span><h3 class="serif">引用资料</h3></div>
      <button class="icon-button" aria-label="关闭引用资料" @click="emit('close')"><el-icon><Close /></el-icon></button>
    </header>
    <div class="source-scroll">
      <article v-for="source in items" :key="source.key" class="source-card" :class="{ active: source.number === activeNumber }">
        <div class="source-number">{{ source.number }}</div>
        <div class="source-content">
          <div class="source-kind">{{ source.kind === 'web' ? '网络资料' : '知识库' }}</div>
          <h4>{{ source.title }}</h4>
          <p v-if="source.location">{{ source.location }}</p>
          <p class="excerpt">{{ source.content?.slice(0, 150) }}</p>
          <a v-if="source.kind === 'web'" :href="source.url" v-bind="attrs"><el-icon><Link /></el-icon> 打开网页</a>
          <button v-else class="text-button" @click="selected = source">定位原文</button>
        </div>
      </article>
      <div v-if="!items.length" class="drawer-empty">这条回答没有引用外部资料</div>
    </div>
    <el-dialog v-model="selected" :title="selected?.title" width="72vw" top="6vh" append-to-body destroy-on-close>
      <DocumentViewer v-if="selected" :source="selected" />
    </el-dialog>
  </aside>
</template>

<style scoped>
.source-drawer { width:0; opacity:0; overflow:hidden; border-left:0 solid var(--hairline); background:#fbfaf5; transition:width .28s ease,opacity .2s ease; flex-shrink:0; }
.source-drawer.open { width:340px; opacity:1; border-left-width:1px; }
header { min-width:340px; height:72px; padding:15px 17px 12px 20px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--hairline-soft); }
.eyebrow { font:9px/1.2 Georgia,serif; letter-spacing:.2em; color:var(--seal); }
h3 { font-size:17px; margin-top:2px; }
.icon-button { border:0; background:transparent; color:var(--ink-3); cursor:pointer; padding:7px; }
.source-scroll { min-width:340px; height:calc(100% - 72px); overflow:auto; padding:14px; }
.source-card { display:flex; gap:11px; padding:13px 10px; border-bottom:1px solid var(--hairline-soft); }
.source-card.active { background:var(--accent-wash); border-radius:9px; }
.source-number { width:24px; height:24px; border-radius:50%; background:var(--accent); color:white; display:grid; place-items:center; font:600 12px Georgia,serif; flex:0 0 auto; }
.source-content { min-width:0; }
.source-kind { color:var(--ink-3); font-size:10px; letter-spacing:.12em; }
h4 { font-size:13px; margin:3px 0 4px; color:var(--ink); }
p { font-size:11px; color:var(--seal); margin:0 0 5px; }
.excerpt { color:var(--ink-2); line-height:1.55; }
a,.text-button { color:var(--accent-deep); font-size:12px; text-decoration:none; display:inline-flex; align-items:center; gap:4px; }
.text-button { border:0; border-bottom:1px solid rgba(46,86,79,.25); background:transparent; padding:2px 0; cursor:pointer; }
.drawer-empty { color:var(--ink-3); text-align:center; padding:48px 20px; font-size:13px; }
</style>
