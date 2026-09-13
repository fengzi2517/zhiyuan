import { describe, expect, it } from 'vitest'
import { validateFiles, attachmentBlocker, normalizeModelOptions } from './attachments'
describe('attachment composition', () => {
  it('rejects excess count, bytes and unsupported files before uploading', () => {
    expect(validateFiles([{ name: 'x.exe', size: 1 }])).toBeTruthy()
    expect(validateFiles(Array.from({ length: 6 }, () => ({ name: 'x.pdf', size: 1 })))).toBeTruthy()
    expect(validateFiles([{ name: 'x.pdf', size: 21 * 1024 ** 2 }])).toBeTruthy()
    expect(validateFiles(Array.from({ length: 3 }, () => ({ name: 'x.pdf', size: 19 * 1024 ** 2 })))).toBeTruthy()
    expect(validateFiles([{ name: 'x.PDF', size: 10 }])).toBe('')
  })
  it('never ignores selected pending, failed or unreadable OCR attachments', () => {
    expect(attachmentBlocker([{ status: 'running' }], true)).toBeTruthy()
    expect(attachmentBlocker([{ status: 'failed' }], true)).toBeTruthy()
    const image = { status: 'ready', is_image: true, ocr_available: false }
    expect(attachmentBlocker([image], false)).toBeTruthy()
    expect(attachmentBlocker([image], true)).toBe('')
  })
  it('disables unsupported settings and defaults vision on for capable models', () => {
    expect(normalizeModelOptions({ supports_vision: false }, { thinkingMode: 'deep', visionEnabled: true })).toEqual({ thinkingMode: 'fast', visionEnabled: false })
    expect(normalizeModelOptions({ supports_vision: true, supports_deep_thinking: true }, { thinkingMode: 'deep', visionEnabled: null })).toEqual({ thinkingMode: 'deep', visionEnabled: true })
  })
})
