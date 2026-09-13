import axios from 'axios'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || `http://${globalThis.location?.hostname || '127.0.0.1'}:8000`
let csrfToken = ''
export const csrfHeaders = () => csrfToken ? { 'X-CSRF-Token': csrfToken } : {}
export const clearAuth = () => { csrfToken = '' }

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 180000,
  withCredentials: true,
})
api.interceptors.request.use(request => {
  Object.assign(request.headers, csrfHeaders())
  return request
})
api.interceptors.response.use(response => response, error => {
  if (error.response?.status === 401 && !error.config?.url?.startsWith('/auth/')) {
    clearAuth()
    globalThis.dispatchEvent?.(new Event('rag:unauthorized'))
  }
  return Promise.reject(error)
})
const acceptAuth = response => { csrfToken = response.data.csrf_token; return response.data.user }
export const login = (username, password) => api.post('/auth/login', { username, password }).then(acceptAuth)
export const currentUser = () => api.get('/auth/me').then(acceptAuth)
export const logout = () => api.post('/auth/logout').then(() => clearAuth())
export const listUsers = () => api.get('/admin/users').then(r => r.data)
export const createUser = data => api.post('/admin/users', data).then(r => r.data)
export const disableUser = id => api.post(`/admin/users/${id}/disable`).then(r => r.data)
export const resetPassword = (id, password) => api.post(`/admin/users/${id}/password`, { password }).then(r => r.data)
export const listMembers = id => api.get(`/kbs/${id}/members`).then(r => r.data)
export const setMember = (id, data) => api.put(`/kbs/${id}/members`, data).then(r => r.data)
export const removeMember = (id, userId) => api.delete(`/kbs/${id}/members/${userId}`).then(r => r.data)
export const retryDocument = id => api.post(`/documents/${id}/retry`).then(r => r.data)
export const getDocumentJob = id => api.get(`/documents/${id}/job`).then(r => r.data)

// 向量库
export const listKbs = () => api.get('/kbs').then(r => r.data)
export const createKb = (name, description) => api.post('/kbs', { name, description }).then(r => r.data)
export const deleteKb = (id) => api.delete(`/kbs/${id}`).then(r => r.data)

// 文档
export const listDocs = (kbId) => api.get('/documents', { params: kbId ? { kb_id: kbId } : {} }).then(r => r.data)
export const uploadDoc = (file, kbId) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/upload', form, { params: kbId ? { kb_id: kbId } : {} }).then(r => r.data)
}
export const getDocContent = (id) => api.get(`/documents/${id}/content`).then(r => r.data)
export const getChunkContext = (docId, chunkId) => api.get(`/documents/${docId}/chunks/${chunkId}/context`).then(r => r.data)
export const getOriginalDocumentUrl = (docId) => `${API_BASE_URL}/documents/${docId}/original`

// 向量可视化
export const getKbVectors = (kbId) => api.get(`/kbs/${kbId}/vectors`).then(r => r.data)

// 会话
export const listModels = () => api.get('/models').then(r => r.data)
const attachmentPath = (sid, id = '') => `/sessions/${encodeURIComponent(sid)}/attachments${id === '' ? '' : `/${encodeURIComponent(id)}`}`
export const listAttachments = sid => api.get(attachmentPath(sid)).then(r => r.data)
export const uploadAttachments = (sid, files) => {
  const form = new FormData()
  files.forEach(file => form.append('files', file))
  return api.post(attachmentPath(sid), form).then(r => r.data)
}
export const retryAttachment = (sid, id) => api.post(`${attachmentPath(sid, id)}/retry`).then(r => r.data)
export const removeAttachment = (sid, id) => api.delete(attachmentPath(sid, id)).then(r => r.data)
export const saveAttachment = (sid, id, kbId) => api.post(`${attachmentPath(sid, id)}/save-to-kb`, { kb_id: kbId }).then(r => r.data)
export const getAttachmentContent = (sid, id) => api.get(`${attachmentPath(sid, id)}/content`).then(r => r.data)
export const getAttachmentUrl = (sid, id) => `${API_BASE_URL}${attachmentPath(sid, id)}/original`
export const getAttachmentPreviewUrl = (sid, id) => `${getAttachmentUrl(sid, id)}?preview=true`
export const listSessions = () => api.get('/sessions').then(r => r.data)
export const getSessionMessages = (sid) => api.get(`/sessions/${encodeURIComponent(sid)}/messages`).then(r => r.data)
export const deleteSession = (sid) => api.delete(`/sessions/${encodeURIComponent(sid)}`).then(r => r.data)
export const editMessage = (id, content) => api.put(`/messages/${id}`, { content }).then(r => r.data)
export const getSessionMemory = (sid) => api.get(`/sessions/${encodeURIComponent(sid)}/memory`).then(r => r.data)

// 问答（opts: { kbId, topK, webEnabled, simThreshold, useMemory }）
export const chat = (question, sessionId, opts = {}) =>
  api.post('/chat', {
    question,
    session_id: sessionId,
    kb_id: opts.kbId ?? null,
    top_k: opts.topK ?? 4,
    web_enabled: opts.webEnabled ?? true,
    sim_threshold: opts.simThreshold ?? 0.4,
    use_memory: opts.useMemory ?? true,
    model_id: opts.modelId ?? null,
    thinking_mode: opts.thinkingMode ?? 'fast',
    vision_enabled: opts.visionEnabled ?? false,
    attachment_ids: opts.attachmentIds ?? [],
  }).then(r => r.data)
