import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { IRC } from './IRC'
import { ircConnect } from '../lib/irc-manager'
vi.mock('../lib/irc-manager', async original => ({ ...await original<typeof import('../lib/irc-manager')>(), ircConnect: vi.fn() }))
const chat = { channel: '#RogueFest', nick: 'RogueGuest###', server: 'irc.arynwood.com' }
beforeEach(() => { localStorage.clear(); vi.mocked(ircConnect).mockReset(); vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('not for members'))) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('gives a member only a nickname for the Grove room, and remembers it', () => {
  render(<IRC chat={chat} full={false} />)
  const nick = screen.getByLabelText('Nickname') as HTMLInputElement
  expect(nick.value).toMatch(/^RogueGuest\d{3}$/)
  expect(screen.getByText('#RogueFest')).toBeInTheDocument()
  for (const field of ['Server', 'Port', 'NickServ password', 'Channels']) expect(screen.queryByLabelText(field)).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
  fireEvent.change(nick, { target: { value: 'Rogue Fan' } })
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }))
  expect(ircConnect).toHaveBeenCalledWith({ host: 'irc.arynwood.com', port: 0, nick: 'RogueFan', channels: ['#RogueFest'], publicChat: true })
  cleanup()
  render(<IRC chat={chat} full={false} />)
  expect(screen.getByLabelText('Nickname')).toHaveValue('RogueFan')
})

it('keeps the full client for the host, starting in the Grove room', () => {
  render(<IRC chat={chat} />)
  expect(screen.getByLabelText('Server')).toHaveValue('irc.arynwood.com')
  expect(screen.getByLabelText('Channels')).toHaveValue('#RogueFest')
  expect(screen.getByLabelText('NickServ password')).toBeInTheDocument()
})
