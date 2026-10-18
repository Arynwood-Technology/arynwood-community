// The Grove's preview pane talks to the page it shows through this script: which page is open and
// where it's scrolled, a spot someone points at for a note, the pins of notes already left, and
// fresh styles while a webmaster types. editor.py adds it to previews shown inside the Grove only,
// never to the published site. Messages carry no secrets: the pane checks where each one came from.
(() => {
  if (window.parent === window) return
  const base = __BASE__
  const say = message => { try { window.parent.postMessage(Object.assign({ grove: 'preview' }, message), '*') } catch (e) { /* the pane has gone */ } }
  const words = text => (text || '').replace(/\s+/g, ' ').trim()
  const address = () => {
    let path = location.pathname
    try { path = decodeURIComponent(path) } catch (e) { /* kept as it is */ }
    return (path.startsWith(base) ? path.slice(base.length) : path) || '/'
  }
  const SOLID = /^(img|video|picture|svg|iframe|canvas|input|select|textarea|button|audio)$/i

  // Pins and the outline under the pointer live in a layer of their own, apart from the page's styles.
  let layer = null, root = null
  function overlay() {
    if (layer && layer.isConnected) return root
    layer = document.createElement('grove-preview-layer')
    layer.setAttribute('style', 'all:initial;position:absolute;top:0;left:0;width:0;height:0;z-index:2147483647')
    root = layer.attachShadow({ mode: 'open' })
    root.innerHTML = '<style>' +
      '.outline{position:fixed;pointer-events:none;border:2px solid #ff3d8b;background:rgba(255,61,139,.12);border-radius:4px;box-sizing:border-box;display:none}' +
      '.outline.shown{display:block}.pins{position:absolute;top:0;left:0}' +
      '.pin{all:initial;position:absolute;box-sizing:border-box;min-width:28px;height:28px;padding:0 6px;margin:-28px 0 0 -4px;border-radius:14px 14px 14px 3px;' +
      'background:#ff3d8b;color:#fff;font:700 13px/28px system-ui,sans-serif;text-align:center;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.35);border:2px solid #fff}' +
      '.pin.done{background:#6b7280}.pin.focused{outline:4px solid rgba(255,61,139,.45);transform:scale(1.15)}' +
      '.pin:focus-visible{outline:3px solid #1d4ed8}' +
      '</style><div class="outline"></div><div class="pins"></div>'
    document.documentElement.appendChild(layer)
    return root
  }
  function outline(el) {
    const box = overlay().querySelector('.outline')
    if (!el) { box.classList.remove('shown'); return }
    const r = el.getBoundingClientRect()
    Object.assign(box.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' })
    box.classList.add('shown')
  }

  // What a spot is: the element under it, or the nearest one around it with words in it.
  function target(node) {
    let el = node && node.nodeType === 1 ? node : node && node.parentElement
    if (!el || el === layer || el === document.documentElement) return null
    while (el.parentElement && el.parentElement !== document.documentElement && !SOLID.test(el.tagName) && !words(el.textContent)) el = el.parentElement
    return el
  }
  function selectorOf(el) {
    const parts = []
    for (let node = el; node && node.nodeType === 1 && node !== document.documentElement; node = node.parentElement) {
      if (node.id && window.CSS && document.querySelectorAll('#' + CSS.escape(node.id)).length === 1) { parts.unshift('#' + CSS.escape(node.id)); break }
      let n = 1
      for (let sibling = node.previousElementSibling; sibling; sibling = sibling.previousElementSibling) if (sibling.tagName === node.tagName) n++
      parts.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + n + ')')
    }
    return parts.join(' > ')
  }
  function quoteOf(el) {
    if (/^img$/i.test(el.tagName)) return words(el.getAttribute('alt')) || words((el.getAttribute('src') || '').split(/[?#]/)[0].split('/').pop())
    return words(el.textContent).slice(0, 600)
  }

  let picking = false, cursor = null
  function pick(on) {
    picking = on
    if (on && !cursor) {
      cursor = document.createElement('style')
      cursor.textContent = '*{cursor:crosshair!important}'
      document.head ? document.head.appendChild(cursor) : document.documentElement.appendChild(cursor)
    }
    if (!on) { if (cursor) cursor.remove(); cursor = null; outline(null) }
  }
  const swallow = event => { if (!picking) return; event.preventDefault(); event.stopPropagation(); event.stopImmediatePropagation() }
  for (const kind of ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'submit', 'dblclick']) document.addEventListener(kind, swallow, true)
  document.addEventListener('mousemove', event => { if (picking) outline(target(event.target)) }, true)
  document.addEventListener('click', event => {
    if (!picking) return
    swallow(event)
    const el = target(event.target)
    if (!el) return
    const r = el.getBoundingClientRect()
    const within = (value, size) => size ? Math.min(1, Math.max(0, value / size)) : 0
    pick(false)
    say({ type: 'picked', page: address(), selector: selectorOf(el), quote: quoteOf(el), tag: el.tagName.toLowerCase(),
          x: within(event.clientX - r.left, r.width), y: within(event.clientY - r.top, r.height) })
  }, true)
  document.addEventListener('keydown', event => { if (picking && event.key === 'Escape') { swallow(event); pick(false); say({ type: 'pick-cancelled' }) } }, true)

  // Pins: each note's element, found by its path, or by its words once the page has changed.
  let pins = [], focused = '', buttons = new Map(), queued = false
  function find(pin) {
    let el = null
    try { el = pin.selector ? document.querySelector(pin.selector) : null } catch (e) { /* not a selector this browser reads */ }
    const quote = words(pin.quote).slice(0, 80)
    if (el && (!quote || SOLID.test(el.tagName) || words(el.textContent).indexOf(quote) >= 0)) return el
    if (!quote || !document.body) return null
    let found = null
    for (const node of document.body.querySelectorAll('*')) if (node !== layer && words(node.textContent).indexOf(quote) >= 0) found = node
    return found
  }
  function place() {
    queued = false
    if (!pins.length && !buttons.size) return
    const box = overlay().querySelector('.pins'), shown = []
    for (const pin of pins) {
      const el = find(pin), r = el && el.getBoundingClientRect()
      let button = buttons.get(pin.id)
      if (!r || (!r.width && !r.height)) { if (button) { button.remove(); buttons.delete(pin.id) } continue }
      if (!button) {
        button = document.createElement('button')
        button.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); say({ type: 'pin', id: pin.id }) })
        buttons.set(pin.id, button); box.appendChild(button)
      }
      button.className = 'pin' + (pin.done ? ' done' : '') + (pin.id === focused ? ' focused' : '')
      button.textContent = String(pin.n)
      button.title = pin.label || ''
      button.setAttribute('aria-label', 'Note ' + pin.n + (pin.label ? ': ' + pin.label : ''))
      button.style.left = (r.left + window.scrollX + r.width * (pin.x == null ? 0 : pin.x)) + 'px'
      button.style.top = (r.top + window.scrollY + r.height * (pin.y == null ? 0 : pin.y)) + 'px'
      shown.push(pin.id)
    }
    for (const [id, button] of buttons) if (!pins.some(p => p.id === id)) { button.remove(); buttons.delete(id) }
    say({ type: 'placed', ids: shown })
  }
  const later = () => { if (!queued) { queued = true; requestAnimationFrame(place) } }
  window.addEventListener('resize', later)
  window.addEventListener('load', later)
  setInterval(() => { if (pins.length) later() }, 1000)

  let scrolled = 0
  document.addEventListener('scroll', () => {
    if (pins.length) later()
    clearTimeout(scrolled)
    scrolled = setTimeout(() => say({ type: 'scrolled', page: address(), x: window.scrollX, y: window.scrollY }), 150)
  }, true)

  function restyle() {
    for (const link of document.querySelectorAll('link[rel~="stylesheet"][href]')) {
      const url = new URL(link.href, location.href)
      url.searchParams.set('grove-edit', String(Date.now()))
      const next = link.cloneNode()
      next.href = url.href
      next.onload = next.onerror = () => link.remove()
      link.after(next)
    }
  }
  const ready = run => document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', run) : run()
  window.addEventListener('message', event => {
    const m = event.data
    if (event.source !== window.parent || !m || m.grove !== 'host') return
    if (m.type === 'pick') ready(() => pick(!!m.on))
    else if (m.type === 'pins') { pins = Array.isArray(m.pins) ? m.pins : []; ready(later) }
    else if (m.type === 'focus') ready(() => {
      const pin = pins.find(p => p.id === m.id), el = pin && find(pin)
      focused = m.id || ''
      later()
      if (!el) return
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      setTimeout(() => { outline(el); setTimeout(() => { if (!picking) outline(null) }, 1600) }, 400)
    })
    else if (m.type === 'scroll') { const go = () => window.scrollTo(m.x || 0, m.y || 0); ready(go); window.addEventListener('load', go, { once: true }) }
    else if (m.type === 'styles') ready(restyle)
    else if (m.type === 'reload') location.reload()
  })
  ready(() => say({ type: 'page', page: address(), title: document.title }))
})()
