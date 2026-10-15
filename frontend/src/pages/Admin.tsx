import { useEffect, useState } from 'react'
import { History, RefreshCw } from 'lucide-react'
import { api, stamp, type GroveRole, type User } from '../lib/community'
import { describeActivity, type Activity } from '../lib/activity'
import { bytes } from '../lib/files'
import { GenieLamp } from '../components/WishLamp'
import { Modal } from './Workspace'
import './admin.css'

interface Person { id: string; name: string; email: string; host: number; created: string; role: GroveRole; spaces: number; last_active: string | null }
interface GroveSpace { id: string; name: string; created: string; used: number }
interface Wish { id: string; created: string; author_name: string; author_email: string; page: string; space_name: string; body: string; delivery: 'kept' | 'sending' | 'sent' | 'failed' }
interface Page { items: Activity[]; next: number | null }
type Filter = { person: string; space: string }
type SpaceCreation = 'everyone' | 'managers'

const roleNames: Record<GroveRole, string> = { owner: 'Owner', manager: 'Manager', member: 'Member' }
const delivery: Record<Wish['delivery'], string> = { kept: 'Kept here; email is not set up', sending: 'Sending', sent: 'Emailed', failed: 'Kept here; the email failed' }

function logPath({ person, space }: Filter, before?: number) {
  const query = new URLSearchParams()
  if (person) query.set('person', person)
  if (space) query.set('space', space)
  if (before) query.set('before', String(before))
  return '/admin/activity' + (query.toString() ? '?' + query : '')
}

/** Running the Grove: its people and their roles, its spaces, wishes, and everything that happens. */
export function Admin({ user, onChanged }: { user: User; onChanged: () => void }) {
  const owner = user.role === 'owner'
  const [people, setPeople] = useState<Person[]>([]), [spaces, setSpaces] = useState<GroveSpace[]>([]), [wishes, setWishes] = useState<Wish[]>([])
  const [creation, setCreation] = useState<SpaceCreation | null>(null)
  const [log, setLog] = useState<Page | null>(null), [filter, setFilter] = useState<Filter>({ person: '', space: '' })
  const [reload, setReload] = useState(0), [loadingMore, setLoadingMore] = useState(false)
  const [message, setMessage] = useState(''), [error, setError] = useState('')
  const [steppingDown, setSteppingDown] = useState<GroveRole | null>(null)
  const flash = (text: string) => { setMessage(text); setError('') }
  const fail = (e: unknown) => { setError((e as Error).message); setMessage('') }

  useEffect(() => {
    api<Person[]>('/admin/people').then(setPeople).catch(e => setError(e.message))
    api<GroveSpace[]>('/admin/spaces').then(setSpaces).catch(e => setError(e.message))
    api<Wish[]>('/admin/wishes').then(setWishes).catch(e => setError(e.message))
    api<{ space_creation: SpaceCreation }>('/admin/settings').then(s => setCreation(s.space_creation)).catch(e => setError(e.message))
  }, [reload])
  useEffect(() => {
    let active = true
    api<Page>(logPath(filter)).then(page => { if (active) setLog(page) }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [filter, reload])

  async function older() {
    if (!log?.next) return
    setLoadingMore(true)
    try { const page = await api<Page>(logPath(filter, log.next)); setLog(l => ({ items: [...(l?.items ?? []), ...page.items], next: page.next })) }
    catch (e) { fail(e) } finally { setLoadingMore(false) }
  }
  async function changeRole(person: Person, role: GroveRole) {
    try {
      await api(`/admin/people/${person.id}/role`, 'PUT', { role })
      setSteppingDown(null)
      setPeople(list => list.map(p => p.id === person.id ? { ...p, role } : p))
      if (person.id === user.id) { onChanged(); return }
      flash(role === 'owner' ? `${person.name} is now an owner of this Grove.` : role === 'manager' ? `${person.name} is now a manager: they see everything here.` : `${person.name} is now a member.`)
      setReload(n => n + 1)
    } catch (e) { setSteppingDown(null); fail(e) }
  }
  async function saveCreation(value: SpaceCreation) {
    try { await api('/admin/settings', 'PUT', { space_creation: value }); setCreation(value); flash(value === 'managers' ? 'Only owners and managers can start spaces now.' : 'Everyone can start spaces now.'); setReload(n => n + 1) }
    catch (e) { fail(e) }
  }
  const me = people.find(p => p.id === user.id)
  const show = (next: Filter) => { setFilter(next); document.getElementById('grove-activity')?.scrollIntoView?.({ behavior: 'smooth' }) }

  return <div className="workspace">
    <div className="page-heading"><div><span className="eyebrow">This Grove</span><h1>Grove admin</h1>
      <p>{owner ? 'As an owner, you choose who else runs this Grove, and see everything that happens in it.' : 'As a manager, you see everything that happens in this Grove. Its owners change roles and settings.'}</p></div>
      <button className="secondary" onClick={() => setReload(n => n + 1)}><RefreshCw size={15} /> Refresh</button></div>
    {error && <p className="error" role="alert">{error}</p>}
    {message && <p className="notice" role="status">{message}</p>}
    <div className="settings-grid">
      <section className="panel admin-people">
        <h2>People</h2>
        <ul className="member-list">{people.map(p => <li key={p.id}>
          <span className="avatar small" aria-hidden="true">{p.name.charAt(0).toUpperCase()}</span>
          <span className="who"><strong>{p.name}{p.id === user.id ? ' (you)' : ''}</strong><small>{p.email} · {p.spaces} {p.spaces === 1 ? 'space' : 'spaces'}{p.last_active ? ` · active ${stamp(p.last_active)}` : ''}</small></span>
          {owner && !p.host ? <select className="role-select push" aria-label={`Grove role for ${p.name}`} value={p.role}
            onChange={e => { const role = e.target.value as GroveRole; if (p.id === user.id) setSteppingDown(role); else void changeRole(p, role) }}>
            {(['owner', 'manager', 'member'] as const).map(r => <option key={r} value={r}>{roleNames[r]}</option>)}</select>
            : <span className="push role-label">{p.host ? 'Host · Owner' : roleNames[p.role]}</span>}
          <button className="icon-button" aria-label={`Activity of ${p.name}`} title="Show their activity" onClick={() => show({ person: p.id, space: '' })}><History size={16} /></button>
        </li>)}</ul>
        <p className="muted-text">Everyone joins as a member. Managers see everything on this page; owners also choose who is an owner or manager. The host, who set up this server, is always an owner.</p>
      </section>
      <section className="panel">
        <h2>Spaces</h2>
        {owner ? <label className="admin-field">Who can start new spaces<select value={creation ?? 'everyone'} disabled={creation === null} onChange={e => void saveCreation(e.target.value as SpaceCreation)}>
          <option value="everyone">Everyone</option><option value="managers">Owners and managers</option></select></label>
          : <p>{creation === 'managers' ? 'Only owners and managers can start spaces.' : 'Everyone can start spaces.'}</p>}
        <ul className="member-list">{spaces.map(s => <li key={s.id}>
          <span className="who"><strong>{s.name}</strong><small>Started {stamp(s.created)} · {bytes(s.used)} of files</small></span>
          <button className="icon-button push" aria-label={`Activity in ${s.name}`} title="Show what happened here" onClick={() => show({ person: '', space: s.id })}><History size={16} /></button>
        </li>)}</ul>
        <p className="muted-text">Every space is listed, whoever started it.</p>
      </section>
      <section className="panel admin-wide">
        <h2><GenieLamp size={20} /> Wishes</h2>
        {wishes.length ? <ul className="wish-list">{wishes.map(w => <li key={w.id}>
          <p>{w.body}</p>
          <small>{w.author_name} ({w.author_email}) · {stamp(w.created)}{w.page ? ` · ${w.page}` : ''}{w.space_name ? ` · ${w.space_name}` : ''} · <span className={w.delivery === 'failed' ? 'danger' : ''}>{delivery[w.delivery]}</span></small>
        </li>)}</ul> : <p>No wishes yet. Anyone in the Grove can make one with the lamp in the corner.</p>}
      </section>
      <section className="panel admin-wide" id="grove-activity">
        <h2>Activity</h2>
        <div className="admin-filters">
          <label className="admin-field">Person<select value={filter.person} onChange={e => setFilter(f => ({ ...f, person: e.target.value }))}>
            <option value="">Everyone</option>{people.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
          <label className="admin-field">Space<select value={filter.space} onChange={e => setFilter(f => ({ ...f, space: e.target.value }))}>
            <option value="">All spaces</option>{spaces.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        </div>
        {log === null ? <p>Loading…</p> : log.items.length ? <ol className="activity-list">{log.items.map(a => <li key={a.id}><time dateTime={a.at}>{stamp(a.at)}</time><span>{describeActivity(a)}</span></li>)}</ol> : <p>Nothing here yet.</p>}
        {log?.next && <button className="secondary" disabled={loadingMore} onClick={() => void older()}>{loadingMore ? 'Loading…' : 'Show older'}</button>}
        <p className="muted-text">Private notes and tasks stay private: the log shows only that they exist, never what they say.</p>
      </section>
    </div>
    {steppingDown && me && <Modal title={steppingDown === 'manager' ? 'Become a manager?' : 'Stop running this Grove?'} onClose={() => setSteppingDown(null)}>
      <p>{steppingDown === 'manager' ? 'You will still see everything here, but no longer change roles or settings.' : 'You will lose access to Grove admin.'} Another owner can make you an owner again.</p>
      <div className="action-row"><button className="danger-button" onClick={() => void changeRole(me, steppingDown)}>{steppingDown === 'manager' ? 'Become a manager' : 'Become a member'}</button><button className="secondary" onClick={() => setSteppingDown(null)}>Cancel</button></div>
    </Modal>}
  </div>
}
