import { describe, expect, it } from 'vitest'
import { shouldPollDocuments } from './polling'


describe('shouldPollDocuments', () => {
  it('polls only while at least one document is pending', () => {
    expect(shouldPollDocuments([{ status: 'done' }, { status: 'failed' }])).toBe(false)
    expect(shouldPollDocuments([{ status: 'done' }, { status: 'pending' }])).toBe(true)
  })
})

