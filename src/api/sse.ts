// Reads a server-sent-events stream that arrives as the body of an ordinary fetch() response.
// (EventSource cannot be used here: it can only send GET, and a reading is a POST that carries two photos.)
//
// Servers differ in small ways, so this is forgiving about them:
//   - lines may end in \n, \r\n or \r, and the \r and \n of one line break may arrive in different chunks
//   - a letter of a multi-byte character may be split across two chunks
//   - comment lines (": ping") and blank blocks are keep-alives and are ignored
//   - a last event that the server forgot to end with a blank line is still delivered

import { ApiError } from './errors'

export type EventHandler = (name: string, data: unknown) => void

/** One event block in, its name and data out. null for blocks that carry no data (keep-alive pings). */
function parseBlock(block: string): { name: string; data: string } | null {
  let name = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    // the format says a single space after the colon is not part of the value
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') name = value.trim()
    else if (field === 'data') data.push(value)
  }
  return data.length ? { name, data: data.join('\n') } : null
}

const unix = (text: string) => text.replace(/\r\n?/g, '\n')

export async function readEventStream(body: ReadableStream<Uint8Array>, onEvent: EventHandler): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (block: string) => {
    const event = parseBlock(block)
    if (!event) return
    let data: unknown
    try {
      data = JSON.parse(event.data)
    } catch {
      throw new ApiError('processing_failed', 'The server sent something we could not read. Nothing was saved. Please try again.')
    }
    onEvent(event.name, data)
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // Turn every kind of line break into \n. A final \r is held back, because its \n may be in the next chunk.
      const held = buffer.endsWith('\r') ? '\r' : ''
      buffer = unix(buffer.slice(0, buffer.length - held.length)) + held
      let end: number
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, end)
        buffer = buffer.slice(end + 2)
        dispatch(block)
      }
    }
    buffer = unix(buffer + decoder.decode())
    if (buffer.trim()) dispatch(buffer)
  } finally {
    // stop reading when we leave early (an error event, a cancelled request), and do nothing if the stream already ended
    reader.cancel().catch(() => {})
  }
}
