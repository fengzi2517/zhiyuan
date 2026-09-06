<script setup>
import { computed } from 'vue'
import { settings, saveSettings } from '../settings'
import { ElMessage } from 'element-plus'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue'])

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

function onSave() {
  saveSettings()
  ElMessage.success('设置已保存')
  visible.value = false
}
</script>

<template>
  <el-dialog v-model="visible" title="问答设置" width="520px" top="4vh" append-to-body>
    <div class="setting-section"><div class="section-title serif">检索</div>
    <el-form label-position="top">
      <el-form-item label="检索片段数量 top_k">
        <el-slider v-model="settings.topK" :min="1" :max="10" show-input
                   input-size="small" style="width: 100%" />
      </el-form-item>
      <el-form-item label="相似度阈值">
        <el-slider v-model="settings.simThreshold" :min="0.3" :max="0.8" :step="0.05"
                   show-input input-size="small" style="width: 100%" />
        <span class="tip">低于该相似度的知识库片段将被过滤，越高越严格</span>
      </el-form-item>
    </el-form></div>
    <div class="setting-section"><div class="section-title serif">回答路径</div>
    <el-form label-position="top">
      <el-form-item label="允许联网">
        <el-switch v-model="settings.webEnabled" />
        <span class="tip">开启后仍会先判断问题；只有时效或资料需求才访问网络</span>
      </el-form-item>
      <el-form-item label="流式显示">
        <el-switch v-model="settings.streamEnabled" />
        <span class="tip">逐字显示回答，并同步展示处理阶段</span>
      </el-form-item>
      <el-form-item label="长期记忆">
        <el-switch v-model="settings.useMemory" />
        <span class="tip">自动归纳会话要点，长对话不遗忘早期内容</span>
      </el-form-item>
    </el-form></div>
    <div class="setting-section"><div class="section-title serif">输入</div>
    <el-form label-position="top">
      <el-form-item label="Enter 快捷发送">
        <el-switch v-model="settings.enterSend" />
      </el-form-item>
    </el-form></div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.setting-section { padding: 4px 0 14px; margin-bottom: 12px; border-bottom: 1px solid var(--hairline-soft); }
.setting-section:last-of-type { border-bottom: 0; }
.section-title { color: var(--seal); font-weight: 700; font-size: 13px; letter-spacing: .14em; margin-bottom: 12px; }
.tip { color: var(--ink-3); font-size: 12px; margin-left: 12px; letter-spacing: 0.02em; }
.setting-section :deep(.el-form-item) { margin-bottom: 16px; }
:global(.el-dialog:has(.setting-section) .el-dialog__body) { max-height: 76vh; overflow: auto; }
</style>
