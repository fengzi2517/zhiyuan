<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import { listKbs, createKb, deleteKb, getKbVectors, listMembers, setMember, removeMember } from '../api'
import { escapeHtml } from '../security'

const kbs = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const form = ref({ name: '', description: '' })
const memberKb = ref(null)
const members = ref([])
const memberForm = ref({ user_id: 1, role: 'reader' })
async function showMembers(kb) {
  try { members.value = await listMembers(kb.id); memberKb.value = kb }
  catch (e) { ElMessage.error(e.response?.data?.detail || '加载成员失败') }
}
async function saveMember() {
  try { await setMember(memberKb.value.id, memberForm.value); await showMembers(memberKb.value) }
  catch (e) { ElMessage.error(e.response?.data?.detail || '保存成员失败') }
}
async function deleteMember(member) {
  try { await ElMessageBox.confirm('移除此成员的知识库权限？', '移除成员'); await removeMember(memberKb.value.id, member.user_id); await showMembers(memberKb.value) }
  catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(e.response?.data?.detail || '移除失败') }
}

// 向量可视化
const vizVisible = ref(false)
const vizLoading = ref(false)
const vizKb = ref(null)
const vizInfo = ref({ points: [], docs: [], variance: [] })
const chartEl = ref(null)
const chartHeight = ref(600)   // 图表高度（px），根据窗口可用高度动态计算
let chart = null

// 计算图表可用高度：窗口高度 - 弹窗头部/说明/边距，限制在 300~840 之间
function calcChartHeight() {
  const h = window.innerHeight
  chartHeight.value = Math.max(300, Math.min(h - 230, 840))
}

// 素笺墨线色板：黛青 / 印朱 / 淡金 / 黛蓝 ……
const COLORS = ['#3e6f68', '#b04a32', '#ab8a52', '#5d7a9a', '#7d9b76',
                '#a3707e', '#8b8c6b', '#4e8a8a', '#c48a50', '#6a6f8c']

async function refresh() {
  loading.value = true
  try {
    kbs.value = await listKbs()
  } finally {
    loading.value = false
  }
}

async function onSubmit() {
  if (!form.value.name.trim()) return ElMessage.warning('请输入向量库名称')
  await createKb(form.value.name, form.value.description)
  ElMessage.success('创建成功')
  dialogVisible.value = false
  form.value = { name: '', description: '' }
  refresh()
}

async function onDel(kb) {
  await ElMessageBox.confirm(
    `确定删除向量库「${kb.name}」？其中 ${kb.doc_count} 份资料及向量数据将被一并删除。`,
    '删除确认', { type: 'warning' })
  await deleteKb(kb.id)
  ElMessage.success('已删除')
  refresh()
}

// ---------- 向量可视化 ----------
async function showViz(kb) {
  vizKb.value = kb
  vizVisible.value = true
  vizLoading.value = true
  calcChartHeight()   // 先按当前窗口算好高度，再渲染图表
  try {
    vizInfo.value = await getKbVectors(kb.id)
    await nextTick()
    renderChart()
  } catch (e) {
    ElMessage.error('加载向量数据失败：' + (e.response?.data?.detail || e.message))
  } finally {
    vizLoading.value = false
  }
}

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const { points, docs, variance } = vizInfo.value
  if (!points.length) { chart.clear(); return }

  // 按文档分组（同文档的点同色，形成"知识簇"）
  const groups = docs.map((d, i) => ({
    name: d.filename,
    type: 'scatter',
    symbolSize: 9,
    itemStyle: { color: COLORS[i % COLORS.length], opacity: 0.82 },
    data: points.filter(p => p.doc_id === d.doc_id).map(p => ({
      value: [p.x, p.y], preview: p.preview, chunk_id: p.chunk_id,
    })),
  }))

  chart.setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: '#fdfcf8',
      borderColor: '#e5e0d2',
      textStyle: { color: '#2d2a24', fontSize: 12 },
      formatter: p => {
        const d = p.data
        return `<div style="max-width:340px;white-space:normal;font-size:12px;line-height:1.6">
          <b>#${d.chunk_id}</b> ${escapeHtml(d.preview)}…</div>`
      },
    },
    legend: { type: 'scroll', bottom: 0, textStyle: { fontSize: 11, color: '#66625a' } },
    grid: { left: 40, right: 20, top: 20, bottom: 50 },
    xAxis: { name: 'PC1', nameTextStyle: { fontSize: 11, color: '#9a958a' }, axisLine: { lineStyle: { color: '#d8d2c2' } }, axisLabel: { color: '#9a958a' }, splitLine: { lineStyle: { type: 'dashed', color: '#ece7da' } } },
    yAxis: { name: 'PC2', nameTextStyle: { fontSize: 11, color: '#9a958a' }, axisLine: { lineStyle: { color: '#d8d2c2' } }, axisLabel: { color: '#9a958a' }, splitLine: { lineStyle: { type: 'dashed', color: '#ece7da' } } },
    series: groups,
  }, true)
  chart.resize()
}

function onVizClosed() {
  if (chart) { chart.dispose(); chart = null }
}

// 浏览器窗口缩放时图表自适应
function onWindowResize() {
  calcChartHeight()
  if (chart) chart.resize()
}
onMounted(() => {
  refresh()
  window.addEventListener('resize', onWindowResize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
  if (chart) { chart.dispose(); chart = null }
})
</script>

<template>
  <el-card class="kb-card">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <span class="card-title serif">向量库列表</span>
        <el-button type="primary" @click="dialogVisible = true">新建向量库</el-button>
      </div>
    </template>

    <div class="kb-intro"><span class="serif">一库一域</span><p>按业务主题组织资料。每个库都可以独立查看语义分布，并在问答时作为参考范围。</p></div>

    <el-empty v-if="!loading && !kbs.length" description="暂无向量库，点击右上角创建" />

    <el-row :gutter="16" v-loading="loading">
      <el-col :span="8" v-for="kb in kbs" :key="kb.id" style="margin-bottom: 16px">
        <el-card shadow="hover">
          <div style="display: flex; justify-content: space-between; align-items: center">
            <div class="kb-name"><span class="kb-index">{{ String(kb.id).padStart(2, '0') }}</span><b>{{ kb.name }}</b></div>
            <div>
              <el-button type="primary" size="small" text @click="showViz(kb)">可视化</el-button>
              <el-button v-if="kb.role === 'owner'" size="small" text @click="showMembers(kb)">成员</el-button>
              <el-button v-if="kb.role === 'owner'" type="danger" size="small" text @click="onDel(kb)">删除</el-button>
            </div>
          </div>
          <div style="color: #909399; font-size: 13px; margin: 8px 0; min-height: 20px">
            {{ kb.description || '暂无描述' }}
          </div>
          <el-tag size="small">{{ kb.doc_count }} 份资料 · {{ ({ owner: '所有者', editor: '可编辑', reader: '只读' })[kb.role] }}</el-tag>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="dialogVisible" title="新建向量库" width="420px" append-to-body>
      <el-form label-width="70px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：产品手册 / 内部制度 / 论文集" maxlength="50" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2"
                    placeholder="该库存放哪类资料（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="onSubmit">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog :model-value="!!memberKb" @update:model-value="value => { if (!value) memberKb = null }" title="知识库成员" width="560px" append-to-body>
      <p>按账号 ID 分配权限。账号 ID 可由管理员在账号管理中查看。</p>
      <el-form inline @submit.prevent="saveMember"><el-form-item label="账号 ID"><el-input-number v-model="memberForm.user_id" :min="1" /></el-form-item>
        <el-form-item label="权限"><el-select v-model="memberForm.role" style="width: 110px"><el-option label="只读" value="reader" /><el-option label="编辑" value="editor" /><el-option label="所有者" value="owner" /></el-select></el-form-item>
        <el-button type="primary" native-type="submit">保存</el-button></el-form>
      <el-table :data="members"><el-table-column prop="user_id" label="账号 ID" /><el-table-column prop="role" label="权限" /><el-table-column label="操作"><template #default="{ row }"><el-button text type="danger" @click="deleteMember(row)">移除</el-button></template></el-table-column></el-table>
    </el-dialog>
    <!-- 向量可视化弹窗 -->
    <el-dialog v-model="vizVisible" width="880px" top="4vh" @closed="onVizClosed" class="viz-dialog" append-to-body>
      <template #header>
        <span style="font-weight: 600">向量空间可视化 · {{ vizKb?.name }}</span>
      </template>
      <div v-loading="vizLoading" style="min-height: 420px">
        <el-alert type="info" :closable="false" style="margin-bottom: 10px"
                  :title="`共 ${vizInfo.points.length} 个向量块，PCA 降至二维（保留方差 ${((vizInfo.variance[0] || 0) * 100).toFixed(1)}% + ${((vizInfo.variance[1] || 0) * 100).toFixed(1)}%）。同一文档的知识块颜色相同，位置越近语义越相似；悬停查看块内容。`" />
        <div v-show="vizInfo.points.length" ref="chartEl" class="viz-chart"
             :style="{ height: chartHeight + 'px' }"></div>
        <el-empty v-if="!vizLoading && !vizInfo.points.length"
                  description="该库还没有向量数据，先上传资料" />
      </div>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.kb-card { animation: rise 0.4s ease both; }
.card-title { font-size: 15px; font-weight: 700; color: var(--ink); letter-spacing: 0.08em; }
.kb-intro { display:flex; align-items:baseline; gap:16px; padding:8px 4px 20px; }
.kb-intro span { color:var(--seal); font-size:15px; font-weight:700; letter-spacing:.16em; flex-shrink:0; }.kb-intro p { color:var(--ink-3); font-size:12px; }
.kb-name { display:flex; align-items:center; gap:10px; }.kb-name b { font-size:15px; }.kb-index { color:var(--seal); font:11px/1 Georgia,serif; border-right:1px solid var(--hairline); padding-right:9px; }

/* 可视化图表：宽度占满，高度由 JS 按窗口动态计算（见 chartHeight） */
.viz-chart { width: 100%; }

.kb-card :deep(.el-card) {
  border: 1px solid var(--hairline);
  border-radius: 11px;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.kb-card :deep(.el-card:hover) {
  transform: translateY(-2px);
  border-color: rgba(62, 111, 104, 0.32);
  box-shadow: var(--el-box-shadow-light);
}
</style>
