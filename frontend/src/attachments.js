export function validateFiles(files, existing = []) {
  if (files.length + existing.length > 5) return '每轮最多选择 5 个附件'
  if (files.some(f => !/\.(png|jpe?g|webp|bmp|txt|md|pdf|docx)$/i.test(f.name))) return '支持图片、TXT、MD、PDF、DOCX'
  if (files.some(f => f.size > 20 * 1024 ** 2)) return '单个附件不能超过 20 MB'
  if ([...files, ...existing].reduce((n, f) => n + f.size, 0) > 50 * 1024 ** 2) return '本轮附件总大小不能超过 50 MB'
  return ''
}
export function attachmentBlocker(cards, vision) {
  if (cards.some(c => c.status === 'failed')) return '附件处理失败，请重试或取消选择后发送'
  if (cards.some(c => c.status !== 'ready')) return '正在处理附件，完成后可发送'
  if (!vision && cards.some(c => c.is_image && !c.ocr_available)) return '图片没有可识别文字，请开启视觉模型或取消选择'
  return ''
}
export function normalizeModelOptions(profile, options) {
  return { thinkingMode: profile?.supports_deep_thinking ? options.thinkingMode || 'fast' : 'fast',
    visionEnabled: !!profile?.supports_vision && (options.visionEnabled ?? true) }
}
