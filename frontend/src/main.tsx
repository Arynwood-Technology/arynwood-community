import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App'

const nativeFetch = window.fetch.bind(window)
window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  const url = new URL(raw, location.href)
  if (url.origin === location.origin && url.pathname.startsWith('/api/')) {
    const headers = new Headers(input instanceof Request ? input.headers : undefined)
    new Headers(init?.headers).forEach((value, key) => headers.set(key, value))
    headers.set('X-Community-Request', '1')
    return nativeFetch(input, { ...init, headers })
  }
  return nativeFetch(input, init)
}
createRoot(document.getElementById('root')!).render(<App />)
