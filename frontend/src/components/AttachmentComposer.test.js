// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
import AttachmentComposer from './AttachmentComposer.vue'
import { listAttachments, uploadAttachments } from '../api'

vi.mock('../api', () => ({ listAttachments: vi.fn(), uploadAttachments: vi.fn(),
  retryAttachment: vi.fn(), removeAttachment: vi.fn(), saveAttachment: vi.fn(),
  getAttachmentUrl: () => '/original', getAttachmentPreviewUrl: () => '/original?preview=true' }))
vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn(), warning: vi.fn() } }))

it('retains newly uploaded selection when an earlier list request completes late', async () => {
  let resolveOld
  listAttachments.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
  const card = { id: 'new', filename: 'new.txt', size: 8, status: 'ready' }
  uploadAttachments.mockResolvedValue([card])
  const change = vi.fn(), uploaded = vi.fn()
  const app = createApp(AttachmentComposer, { sessionId: 's1', kbs: [], onChange: change, onUploaded: uploaded })
  app.config.warnHandler = () => {}
  const host = document.createElement('div')
  const component = app.mount(host)
  try {
    await component.addFiles([new File(['contents'], 'new.txt')])
    resolveOld([])
    await Promise.resolve(); await nextTick()
    expect(change.mock.lastCall[0].cards.map(c => c.id)).toEqual(['new'])
    expect(host.textContent).toContain('new.txt')
    expect(uploaded).toHaveBeenCalledOnce()
  } finally { app.unmount() }
})

it('deduplicates an upload already observed by a list response', async () => {
  let resolveList, resolveUpload
  listAttachments.mockImplementationOnce(() => new Promise(resolve => { resolveList = resolve }))
  uploadAttachments.mockImplementationOnce(() => new Promise(resolve => { resolveUpload = resolve }))
  const card = { id: 'same', filename: 'same.txt', size: 8, status: 'ready' }
  const change = vi.fn()
  const app = createApp(AttachmentComposer, { sessionId: 's2', kbs: [], onChange: change })
  app.config.warnHandler = () => {}
  const component = app.mount(document.createElement('div'))
  try {
    const uploading = component.addFiles([new File(['contents'], 'same.txt')])
    resolveList([card]); await Promise.resolve(); await nextTick()
    resolveUpload([card]); await uploading; await nextTick()
    expect(change.mock.lastCall[0].cards.map(c => c.id)).toEqual(['same'])
  } finally { app.unmount() }
})
