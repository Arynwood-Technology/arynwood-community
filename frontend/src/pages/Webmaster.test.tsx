import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { Webmaster, type SiteImport } from './Webmaster'
import { api, type Space } from '../lib/community'
vi.mock('../lib/community', async original => ({ ...await original<typeof import('../lib/community')>(), api: vi.fn() }))
const mocked = vi.mocked(api)
const spaces: Space[] = [{ id: 'crew', name: 'Crew', role: 'owner' }, { id: 'web', name: 'Website team', role: 'member' }]
const job = (extra: Partial<SiteImport> = {}): SiteImport => ({ id: 'i1', space_id: 'web', space_name: 'Website team', url: 'https://roguefestfilmfestival.com/',
  folder: 'Website/roguefestfilmfestival.com', status: 'done', added: 20, changed: 0, unchanged: 0, skipped: 1, bytes: 6 * 1024 * 1024, message: '',
  started: '2026-10-15T09:00:00Z', finished: '2026-10-15T09:01:00Z', notes: { elsewhere: ['player.vimeo.com', 'filmfreeway.com'], skipped: [['/assets/submission-burst.svg', 'the site answered 404']], server: 'cloudflare' }, ...extra })
beforeEach(() => { mocked.mockReset() })
afterEach(() => cleanup())

it('walks through bringing a site in, changing it, and putting it back', async () => {
  mocked.mockResolvedValue([])
  render(<Webmaster spaces={spaces} current="crew" onOpen={vi.fn()} />)
  for (const step of ['Bring your website in', 'Change what you need', 'Put it back on your domain']) expect(screen.getByRole('heading', { name: new RegExp(step) })).toBeInTheDocument()
  expect(screen.getByText(/Account · Workers Scripts · Edit/)).toBeInTheDocument()
  expect(screen.getByText(/Publishing from the Grove will start with sites served by Cloudflare/)).toBeInTheDocument()
  expect(screen.getByLabelText('Keep it in')).toHaveValue('crew')
})

it('starts an import into the chosen space and shows what came in', async () => {
  let list: SiteImport[] = []
  mocked.mockImplementation(async (_path, method) => method === 'POST' ? (list = [job({ status: 'running', added: 3 })], list[0]) : list)
  render(<Webmaster spaces={spaces} current="crew" onOpen={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Website address'), { target: { value: 'roguefestfilmfestival.com' } })
  fireEvent.change(screen.getByLabelText('Keep it in'), { target: { value: 'web' } })
  fireEvent.click(screen.getByRole('button', { name: /Import website/ }))
  expect(await screen.findByText('Importing… 3 files so far')).toBeInTheDocument()
  expect(mocked).toHaveBeenCalledWith('/webmaster/imports', 'POST', { url: 'roguefestfilmfestival.com', space_id: 'web' })
  expect(screen.getByRole('button', { name: /Importing/ })).toBeDisabled()
  list = [job()]
  expect(await screen.findByText('20 new files, 0 changed, 0 the same · 6.0 MB', {}, { timeout: 4000 })).toBeInTheDocument()
  expect(screen.getByText('Left where they are, on other sites: player.vimeo.com, filmfreeway.com')).toBeInTheDocument()
  expect(screen.getByText(/Your site is served by Cloudflare/)).toBeInTheDocument()
})

it('opens an imported site in Files, and says why an import failed', async () => {
  const onOpen = vi.fn()
  mocked.mockResolvedValue([job(), job({ id: 'i0', status: 'failed', message: 'intranet.local is not a public address.' })])
  render(<Webmaster spaces={spaces} onOpen={onOpen} />)
  fireEvent.click(await screen.findByRole('button', { name: /Open in Files/ }))
  expect(onOpen).toHaveBeenCalledWith('web', 'Website/roguefestfilmfestival.com')
  expect(screen.getByRole('alert')).toHaveTextContent('intranet.local is not a public address.')
  await waitFor(() => expect(screen.getByText('1 file not brought in')).toBeInTheDocument())
})
