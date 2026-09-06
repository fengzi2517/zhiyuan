import { reactive } from 'vue'
import { API_BASE_URL } from '../api'


export function createSseParser(onEvent) {
  let buffer = ''
  return {
    feed(chunk) {
      buffer += chunk.replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        let event = 'message'
        const dataLines = []
        for (const line of frame.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
        }
        if (dataLines.length) onEvent({ event, data: JSON.parse(dataLines.join('\n')) })
        boundary = buffer.indexOf('\n\n')
      }
    },
  }
}


export function createChatStreamer(fetchImpl = fetch) {
  let controller = null
  return {
    async start(payload, onEvent) {
      if (controller) controller.abort()
      controller = new AbortController()
      const ownController = controller
      try {
        const response = await fetchImpl(`${API_BASE_URL}/chat/stream`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
          body: JSON.stringify(payload),
          signal: ownController.signal,
        })
        if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`)
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        const parser = createSseParser(onEvent)
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          parser.feed(decoder.decode(value, { stream: true }))
        }
        parser.feed(decoder.decode())
      } catch (error) {
        if (error.name !== 'AbortError') onEvent({ event: 'error', data: { message: error.message } })
      } finally {
        if (controller === ownController) controller = null
      }
    },
    cancel() {
      controller?.abort()
      controller = null
    },
  }
}


export function useChatStream() {
  const state = reactive({ phase: '', content: '', route: '', sources: [], trace: [], error: '', loading: false })
  const streamer = createChatStreamer()
  function start(payload, onEvent) {
    Object.assign(state, { phase: 'understanding', content: '', route: '', sources: [], trace: [], error: '', loading: true })
    return streamer.start(payload, event => {
      if (event.event === 'status') state.phase = event.data.phase
      if (event.event === 'route') state.route = event.data.route
      if (event.event === 'token') { state.phase = 'generating'; state.content += event.data.text }
      if (event.event === 'sources') state.sources = event.data
      if (event.event === 'trace') state.trace = event.data
      if (event.event === 'error') { state.error = event.data.message; state.loading = false }
      if (event.event === 'done') state.loading = false
      onEvent?.(event, state)
    })
  }
  return { state, start, cancel: streamer.cancel }
}
