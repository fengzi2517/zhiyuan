import axios from 'axios'

const api = axios.create({ baseURL: 'http://127.0.0.1:8000', timeout: 180000 })

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

// 向量可视化
export const getKbVectors = (kbId) => api.get(`/kbs/${kbId}/vectors`).then(r => r.data)

// 会话
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
  }).then(r => r.data)
