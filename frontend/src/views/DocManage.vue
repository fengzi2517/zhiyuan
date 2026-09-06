<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { View } from '@element-plus/icons-vue'
import { listKbs, listDocs, uploadDoc, getDocContent } from '../api'
import { shouldPollDocuments } from '../polling'

const kbs = ref([])
const selectedKb = ref(null)   // null = 全部
const docs = ref([])
const uploading = ref(false)
let timer = null

// 资料查看
const viewerVisible = ref(false)
const viewerLoading = ref(false)
const viewerDoc = ref({ filename: '', content: '' })

async function refreshKbs() {
  kbs.value = await listKbs()
}

async function refreshDocs() {
  docs.value = await listDocs(selectedKb.value)
  ensurePolling()
}

// 有处理中的文档时每 5 秒轮询
function ensurePolling() {
  clearInterval(timer)
  if (shouldPollDocuments(docs.value)) {
    timer = setInterval(() => refreshDocs().catch(() => clearInterval(timer)), 5000)
  }
}

async function refresh() {
  await refreshDocs()
}

async function onUpload(opt) {
  uploading.value = true
  try {
    await uploadDoc(opt.file, selectedKb.value)
    ElMessage.success('上传成功，后台处理中')
    await refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function viewDoc(row) {
  viewerVisible.value = true
  viewerLoading.value = true
  try {
    viewerDoc.value = await getDocContent(row.id)
  } catch (e) {
    viewerDoc.value = { filename: row.filename, content: '加载失败：' + (e.response?.data?.detail || e.message) }
  } finally {
    viewerLoading.value = false
  }
}

function statusTag(s) {
  return s === 'done' ? 'success' : s === 'failed' ? 'danger' : 'warning'
}
function statusText(s) {
  return s === 'done' ? '已完成' : s === 'failed' ? '失败' : '处理中'
}

onMounted(async () => {
  await refreshKbs()
  await refresh()
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <el-card class="doc-card">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px">
        <div style="display: flex; align-items: center; gap: 8px">
          <span class="card-title serif">资料管理</span>
          <el-select v-model="selectedKb" placeholder="全部向量库" clearable
                     style="width: 220px" @change="refresh">
            <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </div>
        <el-upload :show-file-list="false" :http-request="onUpload" :disabled="uploading"
                   accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.bmp,.webp">
          <el-button type="primary" :loading="uploading">
            {{ selectedKb ? '上传到当前库' : '上传（未选库）' }}
          </el-button>
        </el-upload>
      </div>
    </template>

    <el-alert v-if="!selectedKb" type="info" :closable="false" style="margin-bottom: 12px"
              title="未选择向量库时，上传的资料不归属于任何库；问答时选「全部」才会检索到它们" />

    <el-table :data="docs" class="doc-table">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="filename" label="文件名" min-width="240" />
      <el-table-column label="所属库" width="160">
        <template #default="{ row }">
          {{ kbs.find(k => k.id === row.kb_id)?.name ?? '未分类' }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="error_message" label="失败原因" min-width="200" show-overflow-tooltip />
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :icon="View" @click="viewDoc(row)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 资料查看弹窗 -->
    <el-dialog v-model="viewerVisible" width="720px" top="6vh" append-to-body>
      <template #header>
        <span style="font-weight: 600">{{ viewerDoc.filename || '资料查看' }}</span>
      </template>
      <div v-loading="viewerLoading" style="min-height: 200px">
        <el-alert v-if="viewerDoc.content && !viewerDoc.content.trim()"
                  type="info" :closable="false"
                  title="该资料为较早前上传，未保存提取文本；重新上传即可查看" />
        <pre v-else class="doc-content">{{ viewerDoc.content }}</pre>
      </div>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.doc-card { animation: rise 0.4s ease both; }
.card-title { font-size: 15px; font-weight: 700; color: var(--ink); letter-spacing: 0.08em; }

.doc-table :deep(.el-table__row) td {
  border-bottom: 1px solid var(--hairline-soft);
}
.doc-table :deep(td.el-table__cell) { border-bottom: none; }

.doc-content {
  white-space: pre-wrap; word-break: break-word;
  font-family: inherit; font-size: 13.5px; line-height: 1.95; color: var(--ink);
  max-height: 64vh; overflow: auto; background: var(--paper);
  padding: 16px 18px; border-radius: 10px; border: 1px solid var(--hairline-soft);
  margin: 0;
}
</style>
