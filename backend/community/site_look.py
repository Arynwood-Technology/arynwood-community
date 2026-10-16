"""A website's look, read from its files in the Grove: suggestions for Look & feel.

It reads the front page and its stylesheets the way a browser would apply them, closely enough
to find the page's background and text colours, its main button colour, its fonts, its logo
and its share picture. These are suggestions for an owner to review; nothing is saved here."""
import colorsys
import re
from collections import Counter
from html.parser import HTMLParser
from posixpath import normpath
from urllib.parse import unquote, urlsplit
from . import files

TEXT_MAX = 2 * files.MB
HEX = re.compile(r'#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z])')
RULE = re.compile(r'([^{}]+)\{([^{}]*)\}')
DECLARATION = re.compile(r'([-\w]+)\s*:\s*([^;]+)')
VAR = re.compile(r'var\(\s*(--[-\w]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)')
BUTTONS = re.compile(r'\b(btn|button|cta|primary)\b', re.I)
LOGO_LIMIT, PICTURE_LIMIT = 512 * 1024, 2 * 1024 * 1024


class Page(HTMLParser):
    """What the front page says about its look: stylesheets, theme colour, logo and share picture."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sheets, self.styles, self.logos, self.pictures, self.theme = [], [], [], [], ''
        self.header = self.home = self.style = False
    def handle_starttag(self, tag, attrs):
        a = {k: v or '' for k, v in attrs}
        rel = a.get('rel', '').lower().split()
        if tag == 'link' and 'stylesheet' in rel and a.get('href'): self.sheets.append(a['href'])
        if tag == 'link' and 'apple-touch-icon' in rel and a.get('href'): self.logos.append((3, a['href']))
        if tag == 'meta' and a.get('name', '').lower() == 'theme-color': self.theme = a.get('content', '')
        if tag == 'meta' and a.get('property', a.get('name', '')).lower() in ('og:image', 'twitter:image') and a.get('content'): self.pictures.append(a['content'])
        if tag == 'header': self.header = True
        # The site's own logo is in its header, or in its link home; a partner's logo elsewhere isn't.
        if tag == 'a': self.home = a.get('href') in ('/', './', 'index.html') or any(w in a.get('class', '').lower() for w in ('brand', 'logo'))
        if tag == 'img' and a.get('src'):
            hint = any(w in ' '.join((a['src'], a.get('alt', ''), a.get('class', ''))).lower() for w in ('logo', 'brand'))
            if self.header and (hint or self.home): self.logos.append((0, a['src']))
            elif self.header: self.logos.append((1, a['src']))
            elif self.home and hint: self.logos.append((2, a['src']))
        self.style = tag == 'style'
    def handle_endtag(self, tag):
        if tag == 'header': self.header = False
        if tag == 'a': self.home = False
        self.style = False
    def handle_data(self, data):
        if self.style: self.styles.append(data)


def unconditional(css):
    """The stylesheet without its @media and @supports blocks: printing and special cases aren't its usual look."""
    out, depth, skipping, i = [], 0, None, 0
    while i < len(css):
        if skipping is None and css.startswith(('@media', '@supports'), i):
            start = css.find('{', i)
            if start < 0: break
            skipping, depth, i = depth, depth + 1, start + 1
            continue
        ch = css[i]
        if ch == '{': depth += 1
        elif ch == '}':
            depth -= 1
            if skipping is not None and depth == skipping: skipping = None; i += 1; continue
        if skipping is None: out.append(ch)
        i += 1
    return ''.join(out)

def full_hex(value):
    value = value.lower()
    return '#' + ''.join(c * 2 for c in value[1:]) if len(value) == 4 else value

def saturation_of(value):
    hue, lightness, saturation = colorsys.rgb_to_hls(*(int(value[i:i+2], 16) / 255 for i in (1, 3, 5)))
    return saturation, lightness

def font_choice(family, heading):
    family = family.lower()
    if heading and any(name in family for name in ('impact', 'arial black', 'haettenschweiler', 'anton', 'bebas', 'oswald')): return 'bold'
    if any(name in family for name in ('rounded', 'nunito', 'quicksand', 'varela', 'comfortaa')): return 'rounded'
    if 'serif' in family.replace('sans-serif', '') or any(name in family for name in ('georgia', 'times', 'garamond', 'palatino', 'playfair', 'merriweather', 'lora')): return 'classic'
    return 'clean'

def read(c, sid, folder):
    def find(path):
        """A file in the site from an address in its pages: /img/a.png, img/a.png or https://anywhere/img/a.png."""
        path = normpath(unquote(urlsplit(path).path).lstrip('/')) if path else ''
        if not path or path.startswith('..') or path == '.': return None
        parent, _, name = files.joined(folder, path).rpartition('/')
        return c.execute("SELECT id,name,blob,size FROM files WHERE space_id=? AND folder=? AND name=? AND kind='file' AND deleted IS NULL",
                         (sid, parent, name)).fetchone()
    def text(row):
        return files.blob_path(row['blob']).read_bytes()[:TEXT_MAX].decode('utf-8', 'replace') if row and row['size'] <= TEXT_MAX else ''
    page = Page()
    page.feed(text(find('index.html')))
    css = unconditional(re.sub(r'/\*.*?\*/', '', '\n'.join(page.styles + [text(find(href)) for href in page.sheets[:10]]), flags=re.S))
    rules = [([s.strip().lower() for s in selectors.split(',')], {k.lower(): v.strip() for k, v in DECLARATION.findall(body)})
             for selectors, body in RULE.findall(css)]
    custom = {k: v for _, decls in rules for k, v in decls.items() if k.startswith('--')}
    def resolve(value, depth=0):
        if depth > 5: return value
        return VAR.sub(lambda m: resolve(custom.get(m[1], m[2] or ''), depth + 1), value)
    def colour_in(value):
        found = HEX.search(resolve(value or ''))
        return full_hex(found[0]) if found else ''
    def declared(selectors, *properties):
        """The last value the page gives these properties on these selectors, as the cascade would."""
        value = ''
        for chosen, decls in rules:
            if any(s in selectors for s in chosen):
                for prop in properties:
                    if decls.get(prop): value = decls[prop]
        return value
    found = {}
    background = colour_in(page.theme) or colour_in(declared(('body', 'html', ':root'), 'background', 'background-color'))
    if background: found['background'] = found['login_background'] = background
    ink = colour_in(declared(('body', 'html', ':root'), 'color'))
    if ink: found['text'] = ink
    # The accent: what the page's buttons are filled with, or else its boldest colour in use.
    buttons = Counter(colour_in(decls.get('background-color') or decls.get('background', '')) for chosen, decls in rules
                      if any(BUTTONS.search(s) for s in chosen))
    buttons.pop('', None)
    everything = Counter(full_hex(m) for m in HEX.findall(resolve(css)))
    bold = [value for value, _ in (buttons.most_common() or everything.most_common())
            if value not in (background, ink) and saturation_of(value)[0] >= .4 and .2 <= saturation_of(value)[1] <= .8]
    if bold: found['accent'] = bold[0]
    heading = resolve(declared(('h1',), 'font-family'))
    body = resolve(declared(('body', 'html'), 'font-family'))
    if heading: found['font_heading'] = font_choice(heading, True)
    if body: found['font_body'] = font_choice(body, False)
    def picture(candidates, limit):
        for candidate in candidates:
            row = find(candidate)
            if row and row['size'] <= limit and files.media_type(row['name']) in ('image/png', 'image/jpeg', 'image/webp'):
                return {'file_id': row['id'], 'name': row['name'], 'space_id': sid}
        return None
    found['logo'] = picture([src for _, src in sorted(page.logos, key=lambda item: item[0])], LOGO_LIMIT)
    found['picture'] = picture(page.pictures, PICTURE_LIMIT)
    return found
