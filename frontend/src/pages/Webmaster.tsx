import { useEffect, useState } from 'react'
import { Eye, FileArchive, FolderOpen, Globe, LoaderCircle, Rocket, Sparkles } from 'lucide-react'
import { api, stamp, type Space, type User } from '../lib/community'
import { bytes, uploadFile, type Listing } from '../lib/files'
import { Modal } from './Workspace'
import './webmaster.css'

export interface SiteImport {
  id: string; space_id: string; space_name: string; url: string; folder: string; status: 'running' | 'done' | 'failed'
  added: number; changed: number; unchanged: number; skipped: number; bytes: number; message: string; started: string; finished: string | null
  notes: { elsewhere?: string[]; skipped?: [string, string][]; server?: string; cloudflare_analytics?: boolean }
}
/** A folder in a space's Website folder with an index.html at its top. */
export interface Site { space_id: string; space_name: string; folder: string; name: string; member: boolean; files: number; bytes: number; updated: string }
/** A website as it was published. */
export interface Release { id: string; space_id: string; space_name: string; folder: string; files: number; bytes: number; user_name: string; created: string; live: boolean; hidden?: string[] }
export interface SiteState { live: Release | null; releases: Release[]; sites: Site[] }
interface Unpacked { space_id: string; folder: string; added: number; changed: number; unchanged: number; skipped: number; bytes: number; skipped_files: [string, string][]; message: string; has_index: boolean }
const count = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`
const host = (url: string) => { try { return new URL(url).host } catch { return url } }

/** The Grove's website. Everyone sees what's live and previews what's coming; owners and webmasters
 *  bring a site in, change it, and publish it at the Grove's address. */
export function Webmaster({ user, spaces, current, onOpen }: { user: User; spaces: Space[]; current?: string; onOpen: (spaceId: string, folder: string) => void }) {
  const editor = !!user.webmaster, address = window.location.host
  const [state, setState] = useState<SiteState | null>(null), [imports, setImports] = useState<SiteImport[] | null>(null)
  const [error, setError] = useState(''), [message, setMessage] = useState(''), [busy, setBusy] = useState(''), [reload, setReload] = useState(0)
  // Spaces may arrive after the page opens: until one is chosen, it's the current one, or the first.
  const [chosen, setSpace] = useState(''), [unpacked, setUnpacked] = useState<Unpacked | null>(null)
  const space = spaces.some(s => s.id === chosen) ? chosen : current ?? spaces[0]?.id ?? ''
  const [publishing, setPublishing] = useState<Site | null>(null), [takingDown, setTakingDown] = useState(false), [ready, setReady] = useState<{ name: string; url: string } | null>(null)
  const running = imports?.some(i => i.status === 'running') ?? false
  const flash = (text: string) => { setMessage(text); setError('') }
  const fail = (e: unknown) => { setError((e as Error).message); setMessage('') }
  useEffect(() => {
    let active = true
    api<SiteState>('/webmaster/site').then(value => { if (active) setState(value) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [reload])
  useEffect(() => {
    if (!editor) return
    let active = true
    const load = () => api<SiteImport[]>('/webmaster/imports').then(list => { if (active) setImports(list) }).catch(e => { if (active) setError(e.message) })
    void load()
    // While an import runs, its progress shows as it goes; once it ends, its site is listed.
    const timer = running ? setInterval(() => void load(), 1500) : undefined
    return () => { active = false; clearInterval(timer); if (running) setReload(n => n + 1) }
  }, [running, editor])
  async function act(name: string, work: () => Promise<unknown>) {
    setBusy(name); setError('')
    try { await work() } catch (e) { fail(e) } finally { setBusy('') }
  }
  const startImport = (event: React.FormEvent<HTMLFormElement>) => { event.preventDefault(); const url = String(new FormData(event.currentTarget).get('url') ?? ''); void act('import', async () => {
    const started = await api<SiteImport>('/webmaster/imports', 'POST', { url, space_id: space }); setImports(list => [started, ...(list ?? [])])
  }) }
  const sendZip = (event: React.FormEvent<HTMLFormElement>) => { event.preventDefault(); const form = event.currentTarget, file = (form.elements.namedItem('zip') as HTMLInputElement).files?.[0]; void act('zip', async () => {
    if (!file || !/\.zip$/i.test(file.name)) throw new Error('Choose a .zip file.')
    await api(`/community/spaces/${space}/folders`, 'POST', { folder: '', name: 'Website' }).catch(() => {}) // already there
    const listing = await api<Listing>(`/community/spaces/${space}/files?` + new URLSearchParams({ folder: 'Website' }))
    const earlier = listing.items.find(i => i.kind === 'file' && i.name === file.name)
    const saved = await uploadFile(space, file, { folder: 'Website', replaces: earlier?.id })
    setUnpacked(await api<Unpacked>('/webmaster/unpack', 'POST', { space_id: space, file_id: saved.id })); form.reset(); setMessage(''); setReload(n => n + 1)
  }) }
  const startPage = () => void act('starter', async () => {
    const made = await api<{ folder: string }>('/webmaster/starter', 'POST', { space_id: space })
    flash(`Your one-page site is in ${made.folder}. Preview it below, change it in Files, and publish it when it’s ready.`); setReload(n => n + 1)
  })
  const preview = (site: Site) => {
    // Opened now, while the click still counts, so no pop-up blocker stops it; the address follows.
    const tab = window.open('', '_blank')
    if (tab) tab.opener = null
    void act('preview:' + site.folder, async () => {
      try { const { url } = await api<{ url: string }>('/webmaster/previews', 'POST', { space_id: site.space_id, folder: site.folder }); if (tab) tab.location.href = url; else setReady({ name: site.name, url }) }
      catch (e) { tab?.close(); throw e }
    })
  }
  const publish = (site: Site) => { setPublishing(null); void act('publish', async () => {
    const release = await api<Release>('/webmaster/publish', 'POST', { space_id: site.space_id, folder: site.folder })
    flash(`${site.name} is live at ${address}.` + (release.hidden?.length ? ` The Grove keeps these addresses for itself, so they aren’t shown: ${release.hidden.join(', ')}.` : '')); setReload(n => n + 1)
  }) }
  const putBack = (release: Release) => void act('release:' + release.id, async () => {
    await api(`/webmaster/releases/${release.id}/live`, 'POST'); flash(`The version published ${stamp(release.created)} is live again.`); setReload(n => n + 1)
  })
  const takeDown = () => { setTakingDown(false); void act('down', async () => {
    await api('/webmaster/live', 'DELETE'); flash(`The website is down. Visitors to ${address} go to the members’ page.`); setReload(n => n + 1)
  }) }

  const live = state?.live, sites = state?.sites ?? []
  const where = <label className="keep-in">Keep it in<select value={space} onChange={e => setSpace(e.target.value)}>{spaces.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
  return <div className="workspace webmaster">
    <div className="page-heading"><div><span className="eyebrow">This Grove</span><h1>{editor ? 'Webmaster tools' : 'Website'}</h1>
      <p>{editor ? `Bring your website in, change it together, preview it, and publish it at ${address}.` : `This Grove’s website, and what its webmasters are working on. Preview it before it’s published.`}</p></div></div>
    {error && <p className="error" role="alert">{error}</p>}
    {message && <p className="notice" role="status">{message}</p>}
    {ready && <p className="notice" role="status">Your preview of {ready.name} is ready: <a href={ready.url} target="_blank" rel="noopener noreferrer">open it</a>.</p>}

    <section className="panel live-site" aria-labelledby="live-heading">
      <h2 id="live-heading"><Globe size={18} aria-hidden="true" /> Live at {address}</h2>
      {!state ? <p>Loading…</p> : live ? <>
        <p><strong>{live.folder}</strong>{live.space_name ? ` from ${live.space_name}` : ''}, published {stamp(live.created)}{live.user_name ? ` by ${live.user_name}` : ''} · {count(live.files, 'file')}, {bytes(live.bytes)}</p>
        <div className="action-row"><a className="primary button-link" href="/" target="_blank" rel="noopener noreferrer">Visit the site</a>
          {editor && <button className="secondary" disabled={!!busy} onClick={() => setTakingDown(true)}>Take it down</button>}</div>
      </> : <p>Nothing is published yet. Visitors to {address} go to the members’ page.</p>}
      {editor && state && state.releases.length > 1 && <details><summary>Earlier versions ({state.releases.length - 1})</summary><ul className="release-list">
        {state.releases.filter(r => !r.live).map(r => <li key={r.id}><span>{r.folder}, published {stamp(r.created)}{r.user_name ? ` by ${r.user_name}` : ''} · {count(r.files, 'file')}</span>
          <button className="secondary" disabled={!!busy} onClick={() => putBack(r)}>Put this back</button></li>)}
      </ul></details>}
    </section>

    {!editor && <section className="panel" aria-labelledby="sites-heading"><h2 id="sites-heading">Preview</h2>
      <SiteList sites={sites} editor={false} busy={busy} onPreview={preview} onPublish={setPublishing} onOpen={onOpen} />
      {state && !sites.length && <p className="muted-text">There’s no website to preview yet.</p>}
      <p className="muted-text">Only this Grove’s owners, and the webmasters they choose, change and publish its website.</p>
    </section>}

    {editor && <ol className="webmaster-steps">
      <li className="panel">
        <h2><span className="step" aria-hidden="true">1</span> Bring your website in</h2>
        <p>Your site’s files go in a space’s <strong>Website</strong> folder. Everyone in that space can see them, and everyone in the Grove can preview the site. Only owners and webmasters change them.</p>
        {spaces.length ? where : <p className="muted-text">Join or start a space to keep your website in.</p>}
        <div className="bring-in">
          <form onSubmit={startImport}>
            <h3>From its address</h3>
            <p>The Grove reads your site the way a visitor’s browser does: the first page, every page it links to on the same address, and the styles, scripts, images and fonts they use. It follows your site’s robots.txt, and never reads other sites.</p>
            <label>Website address<input name="url" required maxLength={2000} placeholder="https://example.com" defaultValue={imports?.[0]?.url ?? ''} key={imports?.[0]?.url ?? ''} /></label>
            <div className="action-row"><button className="primary" disabled={!!busy || running || !space}><Globe size={15} /> {running ? 'Importing…' : 'Import website'}</button></div>
          </form>
          <form onSubmit={sendZip}>
            <h3>From a .zip</h3>
            <p>For a site that isn’t online yet, or one your designer sent you. Zip the folder that holds its <code>index.html</code>. Sending the same .zip again updates what changed.</p>
            <label>Website .zip<input name="zip" type="file" accept=".zip,application/zip" required /></label>
            <div className="action-row"><button className="primary" disabled={!!busy || !space}><FileArchive size={15} /> {busy === 'zip' ? 'Unpacking…' : 'Upload and unpack'}</button></div>
          </form>
          <div>
            <h3>Start with one page</h3>
            <p>No website yet? Start with a page made from this Grove’s name, tagline and colours, with a way in for members. Change anything before you publish it.</p>
            <div className="action-row"><button className="secondary" disabled={!!busy || !space} onClick={startPage}><Sparkles size={15} /> Make a one-page site</button></div>
          </div>
        </div>
        {unpacked && <div className="import-result">
          <p><strong>{unpacked.folder}</strong>: {count(unpacked.added, 'new file')}, {unpacked.changed} changed, {unpacked.unchanged} the same · {bytes(unpacked.bytes)}</p>
          {unpacked.message && <p className="muted-text">{unpacked.message}</p>}
          {!unpacked.has_index && <p className="danger">There’s no index.html at the top of the .zip’s folder, so the site has no front page yet.</p>}
          {!!unpacked.skipped_files.length && <details><summary>{count(unpacked.skipped, 'file')} left out</summary><ul>{unpacked.skipped_files.map(([path, reason]) => <li key={path}><code>{path}</code>: {reason}</li>)}</ul></details>}
          <button className="secondary" onClick={() => onOpen(unpacked.space_id, unpacked.folder)}><FolderOpen size={15} /> Open in Files</button>
        </div>}
        {imports?.map(i => <ImportResult key={i.id} job={i} onOpen={onOpen} />)}
        <details><summary>What an import can’t bring</summary><ul>
          <li>Code that runs on a server, such as what a form sends to, or a shop’s checkout.</li>
          <li>Pages only signed-in visitors see, and pages nothing links to.</li>
          <li>Files kept on other sites, such as a video on Vimeo. They stay where they are, and the import lists them.</li>
        </ul></details>
      </li>
      <li className="panel">
        <h2><span className="step" aria-hidden="true">2</span> Change what you need</h2>
        <ul>
          <li>Open the site in Files. Every page, stylesheet and image is there, laid out as on your domain.</li>
          <li>Open a page or stylesheet and choose <strong>Edit</strong>. Preview the page as you type, then save a new version. Earlier versions stay in Files.</li>
          <li>You can also download a file, edit it elsewhere, and upload it with the same name. Choose <strong>New version</strong>.</li>
          <li>Nothing you change is live until you publish it.</li>
        </ul>
      </li>
      <li className="panel">
        <h2><span className="step" aria-hidden="true">3</span> Preview and publish</h2>
        <p>Preview shows the whole site as visitors will see it, with its links, scripts and 404 page. Publishing puts it at {address} straight away; the members’ page stays at {address}/community.</p>
        <SiteList sites={sites} editor busy={busy} onPreview={preview} onPublish={setPublishing} onOpen={onOpen} />
        {state && !sites.length && <p className="muted-text">No websites yet. A folder in Website with an index.html at its top shows up here.</p>}
        <details><summary>Your own domain, or another host</summary><ul>
          <li>To show your site at your own domain, ask this Grove’s host to move the Grove there. Your site and the members’ page move together.</li>
          <li>To publish it somewhere else, use <strong>Download as a .zip</strong> on the site’s folder in Files, and send it to whoever runs that host.</li>
          <li>Published pages run their scripts apart from the Grove: they can’t see members’ sign-ins, cookies or browser storage.</li>
        </ul></details>
      </li>
    </ol>}

    {publishing && <Modal title={`Publish ${publishing.name}?`} onClose={() => setPublishing(null)}>
      <p>Visitors to {address} see it straight away{live ? ', in place of what’s live now. You can put that back afterwards' : ''}.</p>
      <div className="action-row"><button className="primary" onClick={() => publish(publishing)}><Rocket size={15} /> Publish</button><button className="secondary" onClick={() => setPublishing(null)}>Cancel</button></div>
    </Modal>}
    {takingDown && <Modal title="Take the website down?" onClose={() => setTakingDown(false)}>
      <p>Visitors to {address} go to the members’ page instead. You can put this version back from Earlier versions.</p>
      <div className="action-row"><button className="danger-button" onClick={takeDown}>Take it down</button><button className="secondary" onClick={() => setTakingDown(false)}>Cancel</button></div>
    </Modal>}
  </div>
}

function SiteList({ sites, editor, busy, onPreview, onPublish, onOpen }: { sites: Site[]; editor: boolean; busy: string; onPreview: (site: Site) => void; onPublish: (site: Site) => void; onOpen: (spaceId: string, folder: string) => void }) {
  if (!sites.length) return null
  return <ul className="site-list">{sites.map(site => <li key={site.space_id + site.folder}>
    <span className="who"><strong>{site.name}</strong><small>{site.space_name} · {count(site.files, 'file')}, {bytes(site.bytes)}{site.updated ? ` · changed ${stamp(site.updated)}` : ''}</small></span>
    <span className="action-row">
      <button className="secondary" disabled={busy === 'preview:' + site.folder} onClick={() => onPreview(site)}><Eye size={15} /> Preview</button>
      {site.member && <button className="secondary" onClick={() => onOpen(site.space_id, site.folder)}><FolderOpen size={15} /> {editor ? 'Edit in Files' : 'Open in Files'}</button>}
      {editor && site.member && <button className="primary" disabled={!!busy} onClick={() => onPublish(site)}><Rocket size={15} /> Publish</button>}
    </span>
  </li>)}</ul>
}

function ImportResult({ job, onOpen }: { job: SiteImport; onOpen: (spaceId: string, folder: string) => void }) {
  return <div className={'import-result import-' + job.status}>
    <p><strong>{host(job.url)}</strong> into {job.space_name || 'a space that was deleted'} · {stamp(job.started)}</p>
    {job.status === 'running' ? <p role="status"><LoaderCircle size={15} className="spinning" aria-hidden="true" /> Importing… {count(job.added + job.changed + job.unchanged, 'file')} so far</p>
      : job.status === 'failed' ? <p className="danger" role="alert">{job.message || 'The import failed.'}</p> : <>
        <p>{count(job.added, 'new file')}, {job.changed} changed, {job.unchanged} the same · {bytes(job.bytes)}</p>
        {job.message && <p className="muted-text">{job.message}</p>}
        {!!job.notes.elsewhere?.length && <p className="muted-text">Left where they are, on other sites: {job.notes.elsewhere.join(', ')}</p>}
        {job.notes.cloudflare_analytics && <p className="muted-text">Cloudflare’s analytics script was left out of the pages. Cloudflare adds it to each page as it serves it, so keeping it would count every visit twice.</p>}
        {!!job.notes.skipped?.length && <details><summary>{count(job.skipped, 'file')} not brought in</summary><ul>{job.notes.skipped.map(([path, reason]) => <li key={path}><code>{path}</code>: {reason}</li>)}</ul></details>}
        {job.space_name && <button className="secondary" onClick={() => onOpen(job.space_id, job.folder)}><FolderOpen size={15} /> Open in Files</button>}
      </>}
  </div>
}
