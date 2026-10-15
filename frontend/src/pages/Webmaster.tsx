import { useEffect, useState } from 'react'
import { FolderOpen, Globe, LoaderCircle } from 'lucide-react'
import { api, stamp, type Space } from '../lib/community'
import { bytes } from '../lib/files'
import './webmaster.css'

export interface SiteImport {
  id: string; space_id: string; space_name: string; url: string; folder: string; status: 'running' | 'done' | 'failed'
  added: number; changed: number; unchanged: number; skipped: number; bytes: number; message: string; started: string; finished: string | null
  notes: { elsewhere?: string[]; skipped?: [string, string][]; server?: string; cloudflare_analytics?: boolean }
}
const count = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`
const host = (url: string) => { try { return new URL(url).host } catch { return url } }

/** Instructions and tools for looking after the Grove's website: bring it in, change it, send it back. */
export function Webmaster({ spaces, current, onOpen }: { spaces: Space[]; current?: string; onOpen: (spaceId: string, folder: string) => void }) {
  const [imports, setImports] = useState<SiteImport[] | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const running = imports?.some(i => i.status === 'running') ?? false
  const cloudflare = imports?.some(i => /cloudflare/i.test(i.notes.server ?? '')) ?? false
  useEffect(() => {
    let active = true
    const load = () => api<SiteImport[]>('/webmaster/imports').then(list => { if (active) setImports(list) }).catch(e => { if (active) setError(e.message) })
    void load()
    // While an import runs, its progress shows as it goes.
    const timer = running ? setInterval(() => void load(), 1500) : undefined
    return () => { active = false; clearInterval(timer) }
  }, [running])
  async function start(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('')
    const data = new FormData(event.currentTarget)
    try { const started = await api<SiteImport>('/webmaster/imports', 'POST', { url: String(data.get('url') ?? ''), space_id: String(data.get('space') ?? '') }); setImports(list => [started, ...(list ?? [])]) }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <div className="workspace webmaster">
    <div className="page-heading"><div><span className="eyebrow">This Grove</span><h1>Webmaster tools</h1>
      <p>Keep your website’s files in the Grove, change them together, and send them back to your domain.</p></div></div>
    <ol className="webmaster-steps">
      <li className="panel">
        <h2><span className="step" aria-hidden="true">1</span> Bring your website in</h2>
        <p>The Grove reads your site the way a visitor’s browser does: the first page, every page it links to on the same address, and the styles, scripts, images and fonts they use. It follows your site’s robots.txt, and never reads other sites.</p>
        <form onSubmit={start}>
          <label>Website address<input name="url" required maxLength={2000} placeholder="https://example.com" defaultValue={imports?.[0]?.url ?? ''} key={imports?.[0]?.url ?? ''} /></label>
          <label>Keep it in<select name="space" defaultValue={current}>{spaces.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <small>Everyone in that space can see the files. A space for the people who look after the website works best.</small>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="action-row"><button className="primary" disabled={busy || running || !spaces.length}><Globe size={15} /> {running ? 'Importing…' : 'Import website'}</button></div>
        </form>
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
          <li>Open the site in Files, under <strong>Website</strong> and then its address. Every page, stylesheet and image is there, laid out as on your domain.</li>
          <li>To change something, download it, edit it, and upload it again with the same name. Choose <strong>New version</strong>: the earlier versions are kept, so nothing is lost.</li>
          <li>Pages, styles and scripts show their contents when you open them, so anyone can check a change.</li>
          <li>Importing again brings in whatever changed on the live site as new versions, and deletes nothing.</li>
        </ul>
        <p className="muted-text">An editor for pages and styles, right in the Grove, is coming next.</p>
      </li>
      <li className="panel">
        <h2><span className="step" aria-hidden="true">3</span> Put it back on your domain</h2>
        <h3>Now: hand it over</h3>
        <p>In Files, use <strong>Download as a .zip</strong> on the site’s folder. You get the whole site in one file, laid out as on your domain, for whoever publishes your website.</p>
        <h3>Next: publish from the Grove</h3>
        <p>{cloudflare ? 'Your site is served by Cloudflare. ' : 'Publishing from the Grove will start with sites served by Cloudflare. '}To let the Grove publish it, whoever looks after your domain’s Cloudflare account:</p>
        <ol className="instructions">
          <li>In Cloudflare, opens <strong>My Profile</strong>, then <strong>API Tokens</strong>, chooses <strong>Create Token</strong>, then <strong>Create Custom Token</strong>.</li>
          <li>Gives it one permission, <strong>Account · Workers Scripts · Edit</strong>, for the account that holds the website and nothing else.</li>
          <li>Notes the <strong>Account ID</strong>, and the name of the Worker that serves the site, both under <strong>Workers &amp; Pages</strong>.</li>
          <li>Sends the token to this Grove’s host privately, never in a group email or chat. It is kept in the server’s settings and used only to publish.</li>
        </ol>
        <p className="muted-text">Publishing isn’t switched on yet. Until it is, use the .zip.</p>
      </li>
    </ol>
  </div>
}

function ImportResult({ job, onOpen }: { job: SiteImport; onOpen: (spaceId: string, folder: string) => void }) {
  return <div className={'import-result ' + job.status}>
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
