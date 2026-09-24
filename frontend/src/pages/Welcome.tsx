import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, MessageCircle, CalendarDays, CheckSquare } from 'lucide-react'
import { Logo } from '../components/Logo'
import { api, type User } from '../lib/community'

export function Welcome({ onLogin }: { onLogin: (user: User, usedInvite: boolean) => void }) {
  const invite = new URLSearchParams(location.search).get('invite') || ''
  const navigate = useNavigate()
  const [setup, setSetup] = useState<boolean | null>(null)
  const [joining, setJoining] = useState(Boolean(invite))
  const [mode, setMode] = useState<'login' | 'signup'>(invite ? 'signup' : 'login')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { api<{ setup: boolean }>('/auth/status').then(v => setSetup(v.setup)).catch(e => setError(e.message)) }, [])
  const signup = setup || joining || mode === 'signup'
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setBusy(true)
    const body = Object.fromEntries(new FormData(event.currentTarget))
    try {
      const result = await api<User>(signup ? '/auth/signup' : '/auth/login', 'POST', signup ? { ...body, invite } : body)
      // Signup consumes the invite. After a plain sign-in the URL keeps it so the app can join that space.
      if (!invite) navigate('/', { replace: true })
      onLogin(result, Boolean(signup && invite))
    }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }
  return <div className="welcome">
    <section className="welcome-story"><div className="brand"><span>arynwood <b>community</b></span></div>
      <div><Logo className="welcome-logo" label="Arynwood" /><span className="eyebrow">A place for your people</span><h1>Life, together.</h1><p>Stay in touch. Make plans. Keep things in order.</p>
        <div className="welcome-features"><span><MessageCircle /> Conversations</span><span><CalendarDays /> Shared plans</span><span><CheckSquare /> Everyday life</span></div></div>
      <small>Your space. Your data.</small>
    </section>
    <section className="welcome-form"><span className="badge">Version 0.3</span><h2>{setup ? 'Make yourself at home' : joining ? 'Join your community' : 'Welcome back'}</h2>
      <form onSubmit={submit}>
        {signup && <label>Your name<input name="name" autoComplete="name" required maxLength={80} /></label>}
        {setup && <label>Space name<input name="space" defaultValue="Our home" required maxLength={80} /></label>}
        <label>Email<input type="email" name="email" autoComplete="username" required maxLength={254} /></label>
        <label>Password<input type="password" name="password" minLength={12} maxLength={256} autoComplete={signup ? 'new-password' : 'current-password'} required /></label>
        {signup && <small>Use at least 12 characters.</small>}
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? 'Please wait' : signup ? 'Create account' : 'Sign in'} <ArrowRight size={16} /></button>
        {invite && !setup && !joining && <p className="muted-text">Sign in to join the space you were invited to.</p>}
        {!setup && <button type="button" className="text-button" onClick={() => { setMode(signup ? 'login' : 'signup'); setJoining(!signup && Boolean(invite)) }}>{signup ? 'I already have an account' : 'Create an account'}</button>}
      </form>
    </section>
  </div>
}
