// getRandomValues also works on HTTP LAN origins where randomUUID is unavailable.
export function newSessionId(source = globalThis.crypto) {
  const bytes = source.getRandomValues(new Uint8Array(16))
  return `s${Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')}`
}
