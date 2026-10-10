import { expect, it } from 'vitest'

// The server refuses any change (POST, PUT, PATCH, DELETE) without X-Community-Request, its
// cross-site request guard. lib/community.ts adds it; a page calling fetch directly must too.
const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

function fetchCalls(source: string): string[] {
  const calls: string[] = []
  for (let start = source.indexOf('fetch('); start !== -1; start = source.indexOf('fetch(', start + 1)) {
    let depth = 0, end = start + 'fetch'.length
    for (; end < source.length; end++) {
      if (source[end] === '(') depth++
      else if (source[end] === ')' && --depth === 0) break
    }
    calls.push(source.slice(start, end + 1))
  }
  return calls
}

it('sends the request guard header with every change made by fetch', () => {
  const missing: string[] = []
  let changes = 0
  for (const [file, source] of Object.entries(sources)) {
    for (const call of fetchCalls(source)) {
      if (!/method:\s*(['"`])(POST|PUT|PATCH|DELETE)\1|method,/.test(call)) continue
      changes++
      if (!call.includes("'X-Community-Request'")) missing.push(`${file}: ${call.slice(0, 80)}`)
    }
  }
  expect(changes).toBeGreaterThan(1)
  expect(missing).toEqual([])
})
