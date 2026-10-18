import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { P2PChat } from './P2PChat'
import { shrinkPhoto } from '../lib/messages'
vi.mock('../lib/messages', async original => ({ ...await original<typeof import('../lib/messages')>(), shrinkPhoto: vi.fn() }))

class FakeSocket {
  static OPEN = 1
  static last: FakeSocket
  readyState = 1
  send = vi.fn()
  close = vi.fn()
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  constructor() { FakeSocket.last = this }
}
const sent = () => FakeSocket.last.send.mock.calls.map(([raw]) => JSON.parse(raw as string)).filter(m => m.type === 'send')

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('grove_p2p_contacts', JSON.stringify([{ addr: 'sam.peer', label: 'Sam', color: '#888' }]))
  vi.stubGlobal('WebSocket', FakeSocket)
  Element.prototype.scrollIntoView = vi.fn()
  vi.mocked(shrinkPhoto).mockReset().mockResolvedValue(new Blob(['jpeg'], { type: 'image/jpeg' }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('keeps a chosen picture or file beside the message box until Send', async () => {
  render(<P2PChat />)
  act(() => FakeSocket.last.onmessage?.({ data: JSON.stringify({ type: 'status', connected: true, addr: 'me.peer' }) }))
  fireEvent.click(screen.getByText('Sam'))
  const photo = new File(['raw'], 'festival.jpg', { type: 'image/jpeg' })
  fireEvent.change(screen.getByLabelText('Choose an image'), { target: { files: [photo] } })
  await screen.findByLabelText('Waiting to send')
  expect(shrinkPhoto).toHaveBeenCalledWith(photo, 2048, 2.5 * 1024 * 1024)
  expect(sent()).toEqual([])
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'From the theater' } })
  fireEvent.click(screen.getByLabelText('Send').closest('button')!)
  expect(sent().map(m => [m.dest, m.contentType])).toEqual([['sam.peer', 'image'], ['sam.peer', 'text']])
  expect(sent()[0].content).toMatch(/^data:image\/jpeg;base64,/)
  expect(screen.queryByLabelText('Waiting to send')).toBeNull()
  // A file waits too, and can be taken off before it goes.
  // jsdom's File has no arrayBuffer().
  const notes = Object.assign(new File(['notes'], 'schedule.txt'), { arrayBuffer: async () => new TextEncoder().encode('notes').buffer })
  fireEvent.change(screen.getByLabelText('Choose a file'), { target: { files: [notes] } })
  expect(await screen.findByText('schedule.txt')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Remove attachment' }))
  await waitFor(() => expect(screen.queryByLabelText('Waiting to send')).toBeNull())
  expect(sent()).toHaveLength(2)
})
