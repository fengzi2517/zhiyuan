import { reactive } from 'vue'

const KEY = 'rag-app-settings'

export const defaults = { topK: 4, webEnabled: true, enterSend: true, simThreshold: 0.4, useMemory: true, streamEnabled: true, modelId: null, thinkingMode: 'fast', visionEnabled: null }

const browserStorage = globalThis.localStorage || { getItem: () => null, setItem: () => {} }

export function loadSettings(storage = browserStorage) {
  try {
    return { ...defaults, ...JSON.parse(storage.getItem(KEY) || '{}') }
  } catch {
    return { ...defaults }
  }
}

export const settings = reactive(loadSettings())

export function saveSettings() {
  browserStorage.setItem(KEY, JSON.stringify(settings))
}
