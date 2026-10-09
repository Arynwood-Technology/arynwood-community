import { useState } from 'react'
import { ArrowRight } from 'lucide-react'

/** "Join a Grove": paste the invitation link someone sent, for this Grove or another one. */
export function JoinByLink({ go = (url: string) => window.location.assign(url) }: { go?: (url: string) => void }) {
  const [value, setValue] = useState(''), [error, setError] = useState('')
  function join(event: React.FormEvent) {
    event.preventDefault(); setError('')
    const text = value.trim()
    try {
      const link = new URL(text)
      if (!['http:', 'https:'].includes(link.protocol) || !link.searchParams.get('invite')) throw new Error()
      go(link.href)
    } catch {
      // Just the code from a link: it belongs to this Grove.
      if (/^[A-Za-z0-9_-]{16,128}$/.test(text)) go(`/community?invite=${encodeURIComponent(text)}`)
      else setError('Paste the whole invitation link, starting with https://')
    }
  }
  return <form className="join-by-link" onSubmit={join}>
    <label>Invitation link<input value={value} onChange={e => setValue(e.target.value)} placeholder="https://…/community?invite=…" autoComplete="off" spellCheck={false} maxLength={600} required /></label>
    {error && <p className="error" role="alert">{error}</p>}
    <button className="secondary">Join <ArrowRight size={16} /></button>
  </form>
}
