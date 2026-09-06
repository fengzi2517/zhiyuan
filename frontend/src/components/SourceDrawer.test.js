import { describe, expect, it } from 'vitest'
import { dedupeSources, externalLinkAttrs } from './source-utils'


describe('source drawer helpers', () => {
  it('shows repeated source only once', () => {
    const items = [{ key: 'a', number: 1 }, { key: 'a', number: 1 }, { key: 'b', number: 2 }]
    expect(dedupeSources(items).map(item => item.number)).toEqual([1, 2])
  })

  it('uses safe attributes for web references', () => {
    expect(externalLinkAttrs()).toEqual({ target: '_blank', rel: 'noopener noreferrer' })
  })
})
