"""A Grove's identity: its name and words, colours, type, corners, logo and login picture.

The host gives a Grove its starting identity in the server's settings (GROVE_BRAND_*). Its owners
change any of it in Look & feel: what they save is kept in the database and wins over the host's
values until they reset it. Any colour scheme, light or dark, is adjusted until text, buttons and
borders are readable. The host's own background setting stays dark-only, as it always was."""
import colorsys
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from typing import Literal
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from backend.community import store, files
from backend.community.auth import grove_owner
from backend.community.activity import record
from backend.community.routes import membership

router = APIRouter()
DEFAULT_ACCENT = '#4fd1ab'
LIGHT = .18  # a background brighter than this gets dark text
# System fonts only: nothing is fetched from another site, and every device has a match.
FONTS = {'clean': 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
         'rounded': 'ui-rounded, "SF Pro Rounded", Nunito, "Varela Round", "Arial Rounded MT Bold", system-ui, sans-serif',
         'classic': 'Georgia, "Iowan Old Style", "Palatino Linotype", Palatino, "Times New Roman", serif',
         'bold': 'Impact, Haettenschweiler, "Arial Narrow Bold", "Arial Black", sans-serif'}
CORNERS = {'round': {'--radius': '14px', '--radius-sm': '9px', '--radius-button': '999px', '--radius-lg': '20px'}, 'soft': {'--radius': '8px', '--radius-sm': '6px', '--radius-button': '8px', '--radius-lg': '12px'},
           'square': {'--radius': '2px', '--radius-sm': '2px', '--radius-button': '2px', '--radius-lg': '3px'}}
IMAGES = {'logo': 512 * 1024, 'picture': 2 * 1024 * 1024}
WORDS = {'name': 80, 'tagline': 160, 'site_label': 40, 'shop_label': 40}
COLOURS = ('background', 'text', 'accent', 'login_background')

# Words and addresses -------------------------------------------------------------------------------
def words(value, limit=160):
    value = (value or '').strip()
    return value if value and len(value) <= limit and not any(ord(c) < 32 for c in value) else ''

def address(value):
    """A link: HTTPS, or HTTP on this computer only."""
    try:
        parts = urlsplit(value)
        if not parts.hostname or parts.username or parts.password or parts.port == 0: return ''
        if parts.scheme == 'https' or (parts.scheme == 'http' and parts.hostname in ('localhost', '127.0.0.1', '::1')):
            if not any(c.isspace() for c in value) and '\\' not in value: return value
    except ValueError:
        pass
    return ''

def text(name, default='', limit=160):
    return words(store.setting('BRAND_' + name), limit) or default

def url(name):
    return address(text(name, limit=2048))

# Colour ---------------------------------------------------------------------------------------------
def luminance(colour):
    channels = [int(colour[i:i+2], 16) / 255 for i in (1, 3, 5)]
    return sum(w * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
               for w, v in zip((.2126, .7152, .0722), channels))

def legacy_accent(value):
    """An accent with no background chosen: it must read on the Grove's own dark greens."""
    surfaces = ('#0f1314', '#171c1d', '#202828', '#10302a', '#1d4a47')
    if re.fullmatch(r'#[0-9a-fA-F]{6}', value or ''):
        light = luminance(value)
        if all((light + .05) / (luminance(bg) + .05) >= 4.5 for bg in surfaces): return value.lower()
    return DEFAULT_ACCENT

def accent():
    return legacy_accent(text('ACCENT'))

def colour(value):
    return value.lower() if re.fullmatch(r'#[0-9a-fA-F]{6}', value or '') else ''

def contrast(first, second):
    a, b = sorted((luminance(first), luminance(second)))
    return (b + .05) / (a + .05)

def hls(value):
    return colorsys.rgb_to_hls(*(int(value[i:i+2], 16) / 255 for i in (1, 3, 5)))

def with_lightness(value, lightness):
    hue, _, saturation = hls(value)
    channels = colorsys.hls_to_rgb(hue, max(0, min(1, lightness)), saturation)
    return '#' + ''.join(f'{round(c * 255):02x}' for c in channels)

def shift(value, amount):
    return with_lightness(value, hls(value)[1] + amount)

def nearest(value, passes):
    # Search both directions in 0.1% lightness steps, checking the rounded hex colour.
    if passes(value): return value
    lightness = hls(value)[1]
    for step in range(1, 1001):
        for direction in (-1, 1):
            candidate = with_lightness(value, lightness + direction * step / 1000)
            if passes(candidate): return candidate
    raise ValueError('No accessible colour')

def blend(first, second, amount):
    channels = [round(int(first[i:i+2], 16) * (1 - amount) + int(second[i:i+2], 16) * amount) for i in (1, 3, 5)]
    return '#' + ''.join(f'{value:02x}' for value in channels)

def rgb(value):
    return ', '.join(str(int(value[i:i+2], 16)) for i in (1, 3, 5))

def settled(base):
    """A background text can be read on, nearest the one chosen. Mid-tones, where neither light nor
    dark text reads well, move: darker ones down to the darkness the host's setting has always asked
    for, lighter ones up until dark text reads on them."""
    if luminance(base) <= LIGHT: return nearest(base, lambda value: luminance(value) <= .1), True
    return nearest(base, lambda value: luminance(value) >= .4), False

def palette(base, ink, source):
    """Every colour the members' pages use, from a background, text and accent."""
    base, dark = settled(base)
    if dark:
        raised = lambda amount: nearest(shift(base, amount), lambda value: luminance(value) <= .16)
        surface, surface2 = raised(.035), raised(.07)
        if not ink or luminance(ink) < .5: ink = '#f4f8f6'
    else:
        surface, surface2 = shift(base, .025), nearest(shift(base, -.035), lambda value: luminance(value) >= .33)
        if not ink or luminance(ink) > .2: ink = '#1c2326'
    surfaces = (base, surface, surface2)
    readable = lambda value: all(contrast(value, bg) >= 4.5 for bg in surfaces)
    ink = nearest(ink, readable)
    muted = nearest(shift(ink, -.18 if dark else .2), readable)
    deep = base if dark else ink  # the darkest colour on the page, for text on a light button
    fill = nearest(source, lambda value: max(contrast(value, '#ffffff'), contrast(value, deep)) >= 4.5)
    on_accent = max(('#ffffff', deep), key=lambda value: contrast(value, fill))
    hover = nearest(shift(fill, -.04 if on_accent == '#ffffff' else .04),
                    lambda value: contrast(value, on_accent) >= 4.5)
    link = nearest(source, readable)
    border = lambda value: contrast(value, surface) >= 3
    slate = shift(base, .055 if dark else -.05)
    status = {name: nearest(value[0] if dark else value[1], readable) for name, value in
              {'--success': ('#6fd3a0', '#1f7a4d'), '--warning': ('#e8b86b', '#8a5a00'), '--danger': ('#ff8f8f', '#b42318'),
               '--danger-text': ('#ffb3b3', '#8f1d1d')}.items()}
    tokens = {'--bg': base, '--surface': surface, '--surface2': surface2,
              '--border': nearest(blend(base, ink, .22), border),
              '--border-strong': nearest(blend(base, ink, .4), border),
              '--text': ink, '--text-muted': muted,
              '--plum': shift(base, .02 if dark else -.02),
              '--plum-mid': nearest(shift(source, -.12), lambda value: contrast(value, '#ffffff') >= 4.5),
              '--plum-soft': f'rgba({rgb(fill)}, .16)', '--slate': slate,
              '--accent': fill, '--accent-hover': hover, '--accent-soft': f'rgba({rgb(fill)}, .14)',
              '--accent-text': link, '--accent2': link, '--on-accent': on_accent,
              '--brand-rgb': rgb(fill), '--slate-rgb': rgb(slate), '--welcome-text': ink,
              '--placeholder': muted, '--welcome-accent': link, '--scheme': 'dark' if dark else 'light', **status}
    if not dark:
        tokens |= {'--shadow': '0 1px 2px rgba(16, 24, 40, .06), 0 4px 14px rgba(16, 24, 40, .07)', '--shadow-lg': '0 20px 50px rgba(16, 24, 40, .18)'}
    return tokens

def login(base, source):
    """The login page's story side: its own background, and words that read on it."""
    base, dark = settled(base)
    steps = (.035, .02, .055) if dark else (-.02, -.035, -.06)
    backgrounds = (base, *(nearest(shift(base, step), (lambda value: luminance(value) <= .16) if dark else (lambda value: luminance(value) >= .33)) for step in steps))
    readable = lambda value: all(contrast(value, bg) >= 4.5 for bg in backgrounds)
    ink = nearest('#ffffff' if dark else '#14181b', readable)
    return {'--login-base': base, '--login-bg': backgrounds[1], '--login-bg2': backgrounds[2], '--login-bg3': backgrounds[3], '--login-rgb': rgb(base),
            '--login-text': ink, '--login-muted': nearest(blend(ink, base, .3), readable), '--login-accent': nearest(source, readable),
            '--login-chip': f'rgba({rgb(ink)}, .1)', '--login-chip-border': f'rgba({rgb(ink)}, .14)'}

def theme(look, picture='', complete=False):
    """CSS custom properties for a look: only what differs from the Grove's own, or, for a preview
    shown inside a page with another look, every one of them."""
    tokens = {}
    if look['background']:
        source = look['accent'] or DEFAULT_ACCENT
        tokens |= palette(look['background'], look['text'], source) | login(look['login_background'] or look['background'], source)
    if picture or complete: tokens['--login-image'] = f'url("{picture}")' if picture else 'none'
    for part in ('heading', 'body'):
        if complete or look['font_' + part] != 'clean': tokens['--font-' + part] = FONTS[look['font_' + part]]
    # A display face has one weight, and needs its letters apart.
    if look['font_heading'] == 'bold': tokens |= {'--heading-lighten': '1', '--heading-tight': '0', '--heading-open': '.01em'}
    elif complete: tokens |= {'--heading-lighten': '0', '--heading-tight': '1', '--heading-open': '0em'}
    if complete or look['corners'] != 'round': tokens |= CORNERS[look['corners']]
    if look['logo_shape'] == 'circle': tokens |= {'--logo-radius': '50%', '--logo-fit': 'cover'}
    elif complete: tokens |= {'--logo-radius': '0', '--logo-fit': 'contain'}
    return tokens

# Where a look comes from ---------------------------------------------------------------------------
def host():
    """The host's starting identity, from the server's settings."""
    surface = colour(text('SURFACE'))
    return {'name': text('NAME'), 'tagline': text('TAGLINE'),
            'background': surface if surface and luminance(surface) <= .1 else '',
            'text': colour(text('TEXT')), 'accent': colour(text('ACCENT')), 'login_background': '',
            'font_heading': 'clean', 'font_body': 'clean', 'corners': 'round', 'logo_shape': 'original',
            'site_url': url('SITE_URL'), 'site_label': text('SITE_LABEL'), 'shop_url': url('SHOP_URL'), 'shop_label': text('SHOP_LABEL'),
            'logo': text('LOGO', limit=255), 'picture': ''}

def saved():
    """What the owners chose in Look & feel, if anything."""
    try:
        with store.db() as c: row = c.execute("SELECT value FROM grove_settings WHERE key='brand'").fetchone()
        return json.loads(row['value']) if row else {}
    except (sqlite3.OperationalError, ValueError):
        return {}

def keep(look):
    with store.db() as c:
        if look: c.execute("INSERT OR REPLACE INTO grove_settings VALUES ('brand',?)", (json.dumps(look),))
        else: c.execute("DELETE FROM grove_settings WHERE key='brand'")

def current():
    return host() | saved()

def kind_of(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return 'image/webp'
    return None

def image(name, limit):
    """A picture in the data directory: PNG, JPEG or WebP, within its size."""
    if not name: return None
    directory = store.database_path().parent.resolve()
    try:
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or not path.is_file(): return None
        with path.open('rb') as source: data = source.read(limit + 1)
        if len(data) <= limit and kind_of(data): return data, kind_of(data)
    except (OSError, ValueError, RuntimeError):
        pass
    return None

def picture_address(look, kind, asset):
    # The host's logo keeps its plain address; one an owner uploads names its version, so pages show the new one.
    if not asset: return ''
    return f'/api/brand/{kind}' + (f'?v={look[kind].rsplit("-", 1)[-1].split(".")[0]}' if look[kind].startswith('brand/') else '')

def read_brand():
    look = current()
    asset, picture = image(look['logo'], IMAGES['logo']), image(look['picture'], IMAGES['picture'])
    picture_url = picture_address(look, 'picture', picture)
    tokens = theme(look, picture_url)
    return {'branded': bool(look['name']), 'name': look['name'] or 'Arynwood Grove',
            'tagline': look['tagline'] or 'The Grove, your community – your choices',
            'accent': tokens.get('--accent', legacy_accent(look['accent'])), 'theme': tokens,
            'site_url': look['site_url'], 'site_label': look['site_label'] or 'Website',
            'shop_url': look['shop_url'], 'shop_label': look['shop_label'] or 'Shop',
            'logo_url': picture_address(look, 'logo', asset), 'picture_url': picture_url, '_logo': asset}

@router.get('')
def brand():
    return {key: value for key, value in read_brand().items() if key != '_logo'}

@router.get('/logo')
def brand_logo():
    asset = read_brand()['_logo']
    if not asset: raise HTTPException(404)
    return Response(asset[0], media_type=asset[1])

@router.get('/picture')
def brand_picture():
    asset = image(current()['picture'], IMAGES['picture'])
    if not asset: raise HTTPException(404)
    return Response(asset[0], media_type=asset[1])

# Look & feel: owners only --------------------------------------------------------------------------
class Look(BaseModel):
    name: str = Field(default='', max_length=200)
    tagline: str = Field(default='', max_length=400)
    background: str = Field(default='', max_length=7)
    text: str = Field(default='', max_length=7)
    accent: str = Field(default='', max_length=7)
    login_background: str = Field(default='', max_length=7)
    font_heading: Literal['clean', 'rounded', 'classic', 'bold'] = 'clean'
    font_body: Literal['clean', 'rounded', 'classic'] = 'clean'
    corners: Literal['round', 'soft', 'square'] = 'round'
    logo_shape: Literal['original', 'circle'] = 'original'
    site_url: str = Field(default='', max_length=2048)
    site_label: str = Field(default='', max_length=200)
    shop_url: str = Field(default='', max_length=2048)
    shop_label: str = Field(default='', max_length=200)

def checked(body):
    """A look as the owner typed it, or what's wrong with it."""
    look = body.model_dump()
    for field, limit in WORDS.items():
        if look[field].strip() and not words(look[field], limit): raise HTTPException(422, f'Use up to {limit} characters for the {field.replace("_", " ")}, on one line.')
        look[field] = words(look[field], limit)
    for field in COLOURS:
        if look[field] and not colour(look[field]): raise HTTPException(422, f'Choose the {field.replace("_", " ")} as a colour like #091c32.')
        look[field] = colour(look[field])
    if (look['text'] or look['accent'] or look['login_background']) and not look['background']:
        raise HTTPException(422, 'Choose a background colour to go with the others.')
    for field in ('site_url', 'shop_url'):
        value = look[field].strip()
        if value and not address(value): raise HTTPException(422, f'The {field[:4]} link needs to start with https://.')
        look[field] = address(value)
    return look

def described(look):
    """Look & feel as an owner sees it: the choices, and the pictures in use."""
    brand = read_brand()
    return {'look': {key: look[key] for key in Look.model_fields}, 'custom': bool(saved()), 'theme': brand['theme'],
            'logo_url': brand['logo_url'], 'picture_url': brand['picture_url'], 'sizes': IMAGES}

@router.get('/look')
def look_settings(current_user=Depends(grove_owner)):
    return described(current())

@router.post('/look/preview')
def preview(body: Look, current_user=Depends(grove_owner)):
    look = current() | checked(body)
    return {'theme': theme(look, picture_address(look, 'picture', image(look['picture'], IMAGES['picture'])), complete=True)}

@router.put('/look')
def save_look(body: Look, current_user=Depends(grove_owner)):
    before, look = current(), checked(body)
    keep(saved() | look)
    with store.db() as c:
        record(c, 'look_changed', actor=current_user['id'], changed=[key for key in look if look[key] != before.get(key)])
    return described(current())

@router.delete('/look')
def reset_look(current_user=Depends(grove_owner)):
    """Back to the host's settings. Pictures the owners uploaded go too."""
    for kind in IMAGES: forget(saved().get(kind, ''))
    keep({})
    with store.db() as c: record(c, 'look_reset', actor=current_user['id'])
    return described(current())

def forget(name):
    if name.startswith('brand/'): (store.database_path().parent / name).unlink(missing_ok=True)

def use_image(kind, data, actor):
    if len(data) > IMAGES[kind]: raise HTTPException(413, f'Use a picture of up to {IMAGES[kind] // 1024} KB.')
    mime = kind_of(data)
    if not mime: raise HTTPException(415, 'Use a PNG, JPEG or WebP picture.')
    name = f"brand/{kind}-{hashlib.sha256(data).hexdigest()[:16]}.{mime.split('/')[1].replace('jpeg', 'jpg')}"
    target = store.database_path().parent / name
    target.parent.mkdir(mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as part:
        part.write(data)
    os.replace(part.name, target)
    look = saved()
    if look.get(kind) != name: forget(look.get(kind, ''))
    keep(look | {kind: name})
    with store.db() as c: record(c, 'look_picture_changed', actor=actor, picture=kind)
    return described(current())

@router.put('/look/{kind}')
async def upload_image(kind: Literal['logo', 'picture'], request: Request, current_user=Depends(grove_owner)):
    if int(request.headers.get('content-length') or 0) > IMAGES[kind]: raise HTTPException(413, f'Use a picture of up to {IMAGES[kind] // 1024} KB.')
    data = bytearray()
    async for piece in request.stream():
        data += piece
        if len(data) > IMAGES[kind]: raise HTTPException(413, f'Use a picture of up to {IMAGES[kind] // 1024} KB.')
    return await run_in_threadpool(use_image, kind, bytes(data), current_user['id'])

@router.delete('/look/{kind}')
def remove_image(kind: Literal['logo', 'picture'], current_user=Depends(grove_owner)):
    """No logo, or no login picture, whatever the host's settings say."""
    look = saved()
    forget(look.get(kind, ''))
    keep(look | {kind: ''})
    with store.db() as c: record(c, 'look_picture_changed', actor=current_user['id'], picture=kind, removed=True)
    return described(current())

class FromFile(BaseModel):
    space_id: str = Field(min_length=1, max_length=64)
    file_id: str = Field(min_length=1, max_length=64)

@router.post('/look/{kind}/from-file')
def image_from_file(kind: Literal['logo', 'picture'], body: FromFile, current_user=Depends(grove_owner)):
    """A picture from Files, such as the logo on the Grove's website."""
    with store.db() as c:
        membership(c, body.space_id, current_user['id'])
        f = files.live_item(c, body.space_id, body.file_id, 'file')
    if f['size'] > IMAGES[kind]: raise HTTPException(413, f'Use a picture of up to {IMAGES[kind] // 1024} KB.')
    return use_image(kind, files.blob_path(f['blob']).read_bytes(), current_user['id'])

class FromSite(BaseModel):
    space_id: str = Field(min_length=1, max_length=64)
    folder: str = Field(min_length=1, max_length=4200)

@router.post('/look/from-site')
def from_site(body: FromSite, current_user=Depends(grove_owner)):
    """What a website in Files looks like: suggestions to review, nothing saved."""
    from backend.community import site_look, website
    with store.db() as c:
        membership(c, body.space_id, current_user['id'])
        folder = website.site_folder(c, body.space_id, body.folder)
        return site_look.read(c, body.space_id, folder)
