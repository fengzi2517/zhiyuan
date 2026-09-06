import DOMPurify from 'dompurify'
import { marked } from 'marked'


export function renderSafeMarkdown(markdown) {
  return DOMPurify.sanitize(marked.parse(markdown || '', { breaks: true }))
}


export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}
