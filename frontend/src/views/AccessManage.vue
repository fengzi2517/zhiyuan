<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listUsers, createUser, disableUser, resetPassword } from '../api'
defineProps({ user: { type: Object, required: true } })
const users = ref([])
const busy = ref(false)
const form = ref({ username: '', password: '', is_admin: false })
const refresh = async () => { users.value = await listUsers() }
const report = e => ElMessage.error(typeof e.response?.data?.detail === 'string' ? e.response.data.detail : '操作失败')
async function create() {
  busy.value = true
  try { await createUser(form.value); form.value = { username: '', password: '', is_admin: false }; await refresh(); ElMessage.success('账号已创建') }
  catch (e) { report(e) } finally { busy.value = false }
}
async function disable(row) {
  try { await ElMessageBox.confirm(`停用 ${row.username} 并使其登录失效？`, '停用账号'); await disableUser(row.id); await refresh() }
  catch (e) { if (e !== 'cancel' && e !== 'close') report(e) }
}
async function reset(row) {
  try {
    const { value } = await ElMessageBox.prompt('设置至少 12 个字符的新密码。已有登录将失效。', `重置 ${row.username} 的密码`, { inputType: 'password', inputValidator: v => v?.length >= 12 || '至少 12 个字符' })
    await resetPassword(row.id, value); ElMessage.success('密码已重置')
  } catch (e) { if (e !== 'cancel' && e !== 'close') report(e) }
}
onMounted(() => refresh().catch(report))
</script>
<template>
  <el-card><template #header><span class="serif">团队账号</span></template>
    <p style="color: #807a6f">创建账号后，在知识库的「成员」中分配资料访问权限。</p>
    <el-form inline @submit.prevent="create">
      <el-form-item label="用户名"><el-input v-model="form.username" autocomplete="off" maxlength="120" /></el-form-item>
      <el-form-item label="初始密码"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" placeholder="至少 12 个字符" /></el-form-item>
      <el-form-item><el-checkbox v-model="form.is_admin">账号管理员</el-checkbox></el-form-item>
      <el-form-item><el-button type="primary" native-type="submit" :loading="busy" :disabled="!form.username.trim() || form.password.length < 12">创建账号</el-button></el-form-item>
    </el-form>
    <el-table :data="users"><el-table-column prop="id" label="ID" width="75" /><el-table-column prop="username" label="用户名" />
      <el-table-column label="角色"><template #default="{ row }">{{ row.is_admin ? '管理员' : '成员' }}</template></el-table-column>
      <el-table-column label="状态"><template #default="{ row }">{{ row.disabled ? '已停用' : '正常' }}</template></el-table-column>
      <el-table-column label="操作"><template #default="{ row }"><el-button text @click="reset(row)">重置密码</el-button><el-button v-if="row.id !== user.id && !row.disabled" text type="danger" @click="disable(row)">停用</el-button></template></el-table-column>
    </el-table>
  </el-card>
</template>
