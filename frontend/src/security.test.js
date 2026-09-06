// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { escapeHtml, renderSafeMarkdown } from './security'

describe('renderSafeMarkdown', () => {
  it('removes executable HTML while preserving markdown formatting', () => {
    const html = renderSafeMarkdown(
      '**safe** <img src="x" onerror="alert(1)"><script>alert(2)</script>'
    )
    expect(html).toContain('<strong>safe</strong>')
    expect(html).not.toContain('onerror')
    expect(html).not.toContain('<script')
  })

  it('removes javascript URLs', () => {
    expect(renderSafeMarkdown('[bad](javascript:alert(1))')).not.toContain('javascript:')
  })
})

describe('escapeHtml', () => {
  it('escapes document text used in chart tooltips', () => {
    expect(escapeHtml('<img onerror="alert(1)">')).toBe(
      '&lt;img onerror=&quot;alert(1)&quot;&gt;'
    )
  })
})

