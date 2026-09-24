import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Sun, MessageSquare, MessagesSquare, CalendarDays, ListChecks, House, NotebookPen, Settings as SettingsIcon, LogOut, Mail as MailIcon, Hash, Radio, Plus, Search, Menu, X } from 'lucide-react'
import { Mail as MailPage } from './pages/Mail'
import { IRC } from './pages/IRC'
import { P2PChat } from './pages/P2PChat'
import { Welcome } from './pages/Welcome'
import { Workspace, Modal } from './pages/Workspace'
import { Settings } from './pages/Settings'
import { api, type User, type Space } from './lib/community'
import { useAppStore } from './store/useAppStore'
import { Logo } from './components/Logo'

// Prevents a crashing page from blanking the whole app.
class PageErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (this.state.error) {
      return <div className="empty crash" role="alert">
        <h2>Something went wrong on this page</h2>
        <p className="muted-text">{this.state.error.message}</p>
        <button className="primary" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    }
    return this.props.children
  }
}

const SPACE_KEY = 'community_space'
function rememberedSpace() { try { return localStorage.getItem(SPACE_KEY) || '' } catch { return '' } }
function rememberSpace(id: string) { try { localStorage.setItem(SPACE_KEY, id) } catch { /* storage unavailable */ } }

const nav = [['/', 'Today', Sun], ['/boards', 'Boards', MessageSquare], ['/chat', 'Chat', MessagesSquare], ['/calendar', 'Calendar', CalendarDays], ['/household', 'Household', House], ['/lists', 'Lists', ListChecks], ['/notes', 'Notes', NotebookPen]] as const
type Section = 'today' | 'boards' | 'chat' | 'calendar' | 'household' | 'lists' | 'notes'

function Hub() {
  const location = useLocation(), navigate = useNavigate()
  const [user, setUser] = useState<User | null>(null)
  const [spaces, setSpaces] = useState<Space[] | null>(null)
  const [selected, setSelected] = useState(rememberedSpace)
  const [ready, setReady] = useState(false)
  const [search, setSearch] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [notice, setNotice] = useState('')
  const ircUnread = useAppStore(s => s.ircUnread)
  const p2pUnread = useAppStore(s => Object.values(s.p2pUnread).reduce((a, b) => a + b, 0))

  // Set when sign-up already used the invite, so it is not redeemed a second time.
  const inviteUsed = useRef(false)
  const choose = useCallback((id: string) => { setSelected(id); rememberSpace(id) }, [])

  useEffect(() => { api<User>('/auth/me').then(setUser).catch(() => {}).finally(() => setReady(true)) }, [])
  useEffect(() => {
    const expired = () => { setUser(null); setSpaces(null) }
    window.addEventListener('session-expired', expired)
    return () => window.removeEventListener('session-expired', expired)
  }, [])

  // Load spaces, then accept a pending invite if the signed-in user followed one.
  useEffect(() => {
    if (!user) return
    let active = true
    const invite = inviteUsed.current ? null : new URLSearchParams(location.search).get('invite')
    if (inviteUsed.current) { inviteUsed.current = false; navigate('/', { replace: true }) }
    ;(async () => {
      let list = await api<Space[]>('/community/spaces')
      if (invite) {
        try {
          const joined = await api<Space>('/community/join', 'POST', { token: invite })
          list = await api<Space[]>('/community/spaces')
          if (active) { choose(joined.id); setNotice(`You joined ${joined.name}.`) }
        } catch (e) { if (active) setNotice((e as Error).message) }
        if (active) navigate('/', { replace: true })
      }
      if (active) setSpaces(list)
    })().catch(e => { if (active) { setSpaces([]); setNotice((e as Error).message) } })
    return () => { active = false }
    // The invite is read once per sign-in; later URL changes must not re-run it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  useEffect(() => { setMenuOpen(false) }, [location.pathname])

  if (!ready) return <div className="loading-screen"><Logo className="" /><p>Opening your community...</p></div>
  if (!user) return <Welcome onLogin={(u, usedInvite) => { inviteUsed.current = usedInvite; setUser(u) }} />

  const space = spaces?.find(s => s.id === selected) ?? spaces?.[0]
  const path = location.pathname
  const section: Section | null = path === '/' ? 'today' : (nav.some(([p]) => p === path) ? path.slice(1) as Section : null)
  const logout = async () => {
    try { await api('/auth/logout', 'POST') } catch { /* the session is cleared locally either way */ }
    setUser(null); setSpaces(null); navigate('/')
  }
  async function createSpace(name: string) {
    const created = await api<Space>('/community/spaces', 'POST', { name })
    setSpaces(list => [...(list ?? []), created]); choose(created.id); setCreating(false); navigate('/')
  }
  function leftSpace(id: string) {
    const rest = (spaces ?? []).filter(s => s.id !== id)
    setSpaces(rest); choose(rest[0]?.id ?? ''); navigate('/')
  }
  const badge = (n: number) => n > 0 ? <span className="nav-badge" aria-label={`${n} unread`}>{n > 99 ? '99+' : n}</span> : null

  return <div className={'app-shell' + (menuOpen ? ' menu-open' : '')}>
    <a className="skip-link" href="#main">Skip to content</a>
    <aside className="sidebar" aria-label="Main navigation">
      <div className="brand"><Logo /><span>arynwood <b>community</b></span><button className="icon-button menu-close" aria-label="Close menu" onClick={() => setMenuOpen(false)}><X size={20} /></button></div>
      {spaces && spaces.length > 0 && <div className="space-picker">
        <label htmlFor="space-select">Your space</label>
        <div className="space-row">
          <select id="space-select" value={space?.id ?? ''} onChange={e => { choose(e.target.value); setSearch('') }}>{spaces.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
          <button className="icon-button" aria-label="New space" title="New space" onClick={() => setCreating(true)}><Plus size={17} /></button>
        </div>
      </div>}
      <nav>
        {nav.map(([to, label, Icon]) => <NavLink end={to === '/'} key={to} to={to}><Icon size={18} />{label}</NavLink>)}
        {user.admin ? <>
          <span className="nav-caption">Connections</span>
          <NavLink to="/mail"><MailIcon size={18} />Mail</NavLink>
          <NavLink to="/irc"><Hash size={18} />IRC{badge(ircUnread)}</NavLink>
          <NavLink to="/message"><Radio size={18} />Message{badge(p2pUnread)}</NavLink>
        </> : null}
        <NavLink to="/settings"><SettingsIcon size={18} />Settings</NavLink>
      </nav>
      <div className="sidebar-bottom">
        <span className="avatar" aria-hidden="true">{user.name.charAt(0).toUpperCase()}</span>
        <span className="who"><strong>{user.name}</strong><small>{user.admin ? 'Host' : 'Member'}</small></span>
        <button className="icon-button push" aria-label="Sign out" title="Sign out" onClick={logout}><LogOut size={16} /></button>
      </div>
    </aside>
    <div className="menu-scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />
    <div className="app-body">
      <header className="topbar">
        <button className="icon-button menu-button" aria-label="Open menu" onClick={() => setMenuOpen(true)}><Menu size={20} /></button>
        <strong className="topbar-title">{space?.name ?? 'Arynwood Community'}</strong>
        {section && section !== 'chat' && section !== 'calendar' && <label className="search-box"><Search size={16} aria-hidden="true" /><input type="search" placeholder="Search this space" aria-label="Search this space" value={search} onChange={e => setSearch(e.target.value)} maxLength={200} /></label>}
      </header>
      {notice && <div className="notice banner" role="status">{notice}<button className="icon-button" aria-label="Dismiss" onClick={() => setNotice('')}><X size={15} /></button></div>}
      <main id="main" className={path === '/mail' || path === '/irc' || path === '/message' ? 'full-bleed' : ''}>
        <PageErrorBoundary>
          {spaces === null ? <div className="empty"><p>Opening your space...</p></div>
            : !space && path !== '/mail' && path !== '/irc' && path !== '/message' ? <NoSpace onCreate={createSpace} />
            : <Routes>
              {space && nav.map(([to]) => <Route key={to} path={to} element={<Workspace key={space.id} section={to === '/' ? 'today' : to.slice(1) as Section} space={space} user={user} search={search} />} />)}
              {space && <Route path="/settings" element={<Settings key={space.id} space={space} user={user} onLogout={logout} onLeft={leftSpace} />} />}
              <Route path="/mail" element={user.admin ? <MailPage /> : <Navigate to="/" replace />} />
              <Route path="/irc" element={user.admin ? <IRC /> : <Navigate to="/" replace />} />
              <Route path="/message" element={user.admin ? null : <Navigate to="/" replace />} />
              <Route path="/p2p" element={<Navigate to="/message" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>}
          {/* Message stays mounted so incoming messages keep arriving while you use other pages. */}
          {user.admin ? <div className="persistent-page" hidden={path !== '/message'}><P2PChat /></div> : null}
        </PageErrorBoundary>
      </main>
    </div>
    {creating && <Modal title="New space" onClose={() => setCreating(false)}><SpaceForm onCreate={createSpace} onCancel={() => setCreating(false)} /></Modal>}
  </div>
}

function SpaceForm({ onCreate, onCancel }: { onCreate: (name: string) => Promise<void>; onCancel?: () => void }) {
  const [name, setName] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  return <form onSubmit={async e => {
    e.preventDefault(); setBusy(true); setError('')
    try { await onCreate(name.trim()) } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }}>
    <label>Space name<input value={name} onChange={e => setName(e.target.value)} required maxLength={80} autoFocus placeholder="e.g. The Garden House" /></label>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="action-row"><button className="primary" disabled={busy || !name.trim()}>{busy ? 'Creating' : 'Create space'}</button>{onCancel && <button type="button" className="secondary" onClick={onCancel}>Cancel</button>}</div>
  </form>
}

function NoSpace({ onCreate }: { onCreate: (name: string) => Promise<void> }) {
  return <div className="workspace narrow"><div className="page-heading"><div><span className="eyebrow">Welcome</span><h1>Start a space</h1><p>You are not in any spaces yet. Create one, or open an invite link from someone you know.</p></div></div>
    <section className="panel"><SpaceForm onCreate={onCreate} /></section></div>
}

export default function App() { return <BrowserRouter><Hub /></BrowserRouter> }
