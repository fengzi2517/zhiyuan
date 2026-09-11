import { describe, expect, it, vi } from 'vitest'
import { createSseParser, createChatStreamer } from './useChatStream'


describe('createSseParser', () => {
  it('accepts CRLF split between network chunks', () => {
    const events = []
    const parser = createSseParser(event => events.push(event))
    parser.feed('event: done\r')
    parser.feed('\ndata: {"answer":"ok"}\r')
    parser.feed('\n\r')
    parser.feed('\n')
    expect(events).toEqual([{ event: 'done', data: { answer: 'ok' } }])
  })
  it('joins SSE frames split across network chunks', () => {
    const events = []
    const parser = createSseParser(event => events.push(event))
    parser.feed('event: token\ndata: {"te')
    parser.feed('xt":"你"}\n\nevent: done\ndata: {"answer":"你"}\n\n')
    expect(events).toEqual([
      { event: 'token', data: { text: '你' } },
      { event: 'done', data: { answer: '你' } },
    ])
  })
})


describe('createChatStreamer', () => {
  it('reports a missing terminal event and releases the reader', async () => {
    const releaseLock = vi.fn()
    const read = vi.fn()
      .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('event: token\ndata: {"text":"partial"}\n\n') })
      .mockResolvedValueOnce({ done: true })
    const streamer = createChatStreamer(async () => ({
      ok: true, body: { getReader: () => ({ read, releaseLock }) },
    }))
    const events = []
    await streamer.start({ question: 'q' }, event => events.push(event))
    expect(events.map(event => event.event)).toEqual(['token', 'error'])
    expect(events[1].data.code).toBe('stream_incomplete')
    expect(releaseLock).toHaveBeenCalledOnce()
  })

  it('does not report interrupted old requests as errors', async () => {
    let finishFetch
    const streamer = createChatStreamer(() => new Promise(resolve => { finishFetch = resolve }))
    const events = []
    const pending = streamer.start({ question: 'old' }, event => events.push(event))
    streamer.cancel()
    finishFetch({ ok: false, text: async () => 'old failure' })
    await pending
    expect(events).toEqual([])
  })
  it('aborts the previous request before starting another', async () => {
    const signals = []
    const fetchImpl = vi.fn((_url, options) => {
      signals.push(options.signal)
      return new Promise(() => {})
    })
    const streamer = createChatStreamer(fetchImpl)
    streamer.start({ question: 'first' }, () => {})
    streamer.start({ question: 'second' }, () => {})
    expect(signals[0].aborted).toBe(true)
    streamer.cancel()
    expect(signals[1].aborted).toBe(true)
  })
})
