import { describe, expect, it } from 'vitest'
import { loadSettings } from './settings'
import { summarizeDocuments } from './polling'


describe('settings compatibility', () => {
  it('keeps old values and enables streaming by default', () => {
    const storage = { getItem: () => JSON.stringify({ topK: 7, webEnabled: false }) }
    const loaded = loadSettings(storage)
    expect(loaded.topK).toBe(7)
    expect(loaded.webEnabled).toBe(false)
    expect(loaded.streamEnabled).toBe(true)
  })
})


it('summarizes document workflow states', () => {
  expect(summarizeDocuments([{ status: 'done' }, { status: 'failed' }, { status: 'pending' }]))
    .toEqual({ total: 3, done: 1, failed: 1, pending: 1 })
})
