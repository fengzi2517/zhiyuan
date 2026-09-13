import { expect, it } from 'vitest'
import { newSessionId } from './sessionId'

it('creates distinct conversation IDs on HTTP origins without randomUUID', () => {
  const insecureCrypto = { getRandomValues: array => crypto.getRandomValues(array) }
  const ids = Array.from({ length: 100 }, () => newSessionId(insecureCrypto))
  expect(new Set(ids).size).toBe(100)
  expect(ids.every(id => /^s[0-9a-f]{32}$/.test(id))).toBe(true)
})
