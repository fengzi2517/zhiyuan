export function dedupeSources(sources = []) {
  const seen = new Set()
  return sources.filter(source => {
    const key = source.key || `${source.kind}:${source.number}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function externalLinkAttrs() {
  return { target: '_blank', rel: 'noopener noreferrer' }
}
