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
  <el-dialog v-model="visible" title="设置" width="440px" append-to-body>
    <el-form label-width="140px">
      <el-form-item label="检索片段数量 top_k">
        <el-slider v-model="settings.topK" :min="1" :max="10" show-input
                   input-size="small" style="width: 100%" />
      </el-form-item>
      <el-form-item label="联网搜索兜底">
        <el-switch v-model="settings.webEnabled" />
        <span class="tip">知识库资料不足时，自动联网搜索补充</span>
      </el-form-item>
      <el-form-item label="相似度阈值">
        <el-slider v-model="settings.simThreshold" :min="0.3" :max="0.8" :step="0.05"
                   show-input input-size="small" style="width: 100%" />
        <span class="tip">低于该相似度的知识库片段将被过滤，越高越严格</span>
      </el-form-item>
      <el-form-item label="长期记忆">
        <el-switch v-model="settings.useMemory" />
        <span class="tip">自动归纳会话要点，长对话不遗忘早期内容</span>
      </el-form-item>
      <el-form-item label="Enter 快捷发送">
        <el-switch v-model="settings.enterSend" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.tip { color: var(--ink-3); font-size: 12px; margin-left: 12px; letter-spacing: 0.02em; }
</style>
