import { reactive } from 'vue'

const KEY = 'rag-app-settings'

const defaults = { topK: 4, webEnabled: true, enterSend: true, simThreshold: 0.4, useMemory: true }

function load() {
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(KEY) || '{}') }
  } catch {
    return { ...defaults }
  }
}

export const settings = reactive(load())

export function saveSettings() {
  localStorage.setItem(KEY, JSON.stringify(settings))
}
