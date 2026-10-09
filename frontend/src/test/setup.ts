import '@testing-library/jest-dom/vitest'

// Tests run without a Grove service; anything that reaches the network gets an empty answer.
globalThis.fetch = (async () =>
  new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } })
) as typeof fetch
