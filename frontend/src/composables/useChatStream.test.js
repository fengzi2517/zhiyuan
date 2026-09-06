import { describe, expect, it, vi } from 'vitest'
import { createSseParser, createChatStreamer } from './useChatStream'


describe('createSseParser', () => {
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
