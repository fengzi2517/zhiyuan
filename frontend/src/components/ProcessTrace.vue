<script setup>
defineProps({ trace: { type: Array, default: () => [] }, elapsedMs: Number, activePhase: String })
const labels = { understand: '理解问题', route: '选择处理方式', retrieve: '查找知识库', web_search: '查找网络资料', generate: '组织回答' }
</script>

<template>
  <div class="process-trace" v-if="trace.length || activePhase">
    <div class="process-head">
      <span class="process-kicker">处理过程</span>
      <span v-if="elapsedMs != null" class="process-time">{{ (elapsedMs / 1000).toFixed(1) }} 秒</span>
    </div>
    <div class="process-line">
      <span v-for="(step, index) in trace" :key="index" class="process-step" :title="step.reason || step.mode || ''">
        <i></i>{{ step.label || labels[step.stage] || step.stage }}
        <small v-if="step.elapsed_ms != null">{{ step.elapsed_ms }} ms</small>
        <small v-if="step.first_token_ms != null">首字 {{ step.first_token_ms }} ms</small>
      </span>
      <span v-if="activePhase" class="process-step active"><i></i>{{ activePhase }}</span>
    </div>
  </div>
</template>

<style scoped>
.process-trace { margin: 0 0 12px; padding: 10px 12px; border: 1px solid var(--hairline-soft); background: #faf8f1; border-radius: 9px; }
.process-head { display:flex; justify-content:space-between; margin-bottom:8px; font-size:11px; }
.process-kicker { color:var(--accent-deep); font-weight:700; letter-spacing:.12em; }
.process-time { color:var(--ink-3); font-variant-numeric:tabular-nums; }
.process-line { display:flex; flex-wrap:wrap; gap:8px 14px; }
.process-step { font-size:12px; color:var(--ink-2); display:flex; align-items:center; gap:5px; }
.process-step i { width:6px; height:6px; border-radius:50%; background:#a8b9b5; }
.process-step small { color:var(--ink-3); font-variant-numeric:tabular-nums; }
.process-step.active i { background:var(--seal); box-shadow:0 0 0 4px rgba(176,74,50,.1); animation:pulse 1.4s infinite; }
@keyframes pulse { 50% { transform:scale(.7); opacity:.55; } }
</style>
