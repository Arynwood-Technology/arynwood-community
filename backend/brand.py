"""Public Grove identity. Keep its source behind read_brand for future asset management."""
import re
import colorsys
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from backend.community import store

router = APIRouter()
DEFAULT_ACCENT = '#4fd1ab'

def text(name, default='', limit=160):
    value = store.setting('BRAND_' + name).strip()
    return value if value and len(value) <= limit and not any(ord(c) < 32 for c in value) else default

def url(name):
    value = text(name, limit=2048)
    try:
        parts = urlsplit(value)
        if not parts.hostname or parts.username or parts.password or parts.port == 0: return ''
        if parts.scheme == 'https' or (parts.scheme == 'http' and parts.hostname in ('localhost', '127.0.0.1', '::1')):
            if not any(c.isspace() for c in value) and '\\' not in value: return value
    except ValueError:
        pass
    return ''

def luminance(colour):
    channels = [int(colour[i:i+2], 16) / 255 for i in (1, 3, 5)]
    return sum(w * (v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4)
               for w, v in zip((.2126, .7152, .0722), channels))

def accent():
    value = text('ACCENT')
    surfaces = ('#0f1314', '#171c1d', '#202828', '#10302a', '#1d4a47')
    if re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        light = luminance(value)
        if all((light + .05) / (luminance(bg) + .05) >= 4.5 for bg in surfaces): return value.lower()
    return DEFAULT_ACCENT

def colour(value):
    return value.lower() if re.fullmatch(r'#[0-9a-fA-F]{6}', value) else ''

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

def theme():
    base = colour(text('SURFACE'))
    if not base or luminance(base) > .1: return {}
    raised = lambda amount: nearest(shift(base, amount), lambda value: luminance(value) <= .16)
    surface, surface2 = raised(.035), raised(.07)
    surfaces = (base, surface, surface2)
    readable = lambda value: all(contrast(value, bg) >= 4.5 for bg in surfaces)
    ink = colour(text('TEXT'))
    if not ink or luminance(ink) < .5: ink = '#f4f8f6'
    ink = nearest(ink, readable)
    muted = nearest(shift(ink, -.18), readable)
    source = colour(text('ACCENT')) or DEFAULT_ACCENT
    fill = nearest(source, lambda value: max(contrast(value, '#ffffff'), contrast(value, base)) >= 4.5)
    on_accent = max(('#ffffff', base), key=lambda value: contrast(value, fill))
    hover = nearest(shift(fill, -.04 if on_accent == '#ffffff' else .04),
                    lambda value: contrast(value, on_accent) >= 4.5)
    link = nearest(source, readable)
    border = lambda value: contrast(value, surface) >= 3
    slate = shift(base, .055)
    return {'--bg': base, '--surface': surface, '--surface2': surface2,
            '--border': nearest(blend(base, ink, .22), border),
            '--border-strong': nearest(blend(base, ink, .4), border),
            '--text': ink, '--text-muted': muted,
            '--plum': shift(base, .02),
            '--plum-mid': nearest(shift(source, -.12), lambda value: contrast(value, '#ffffff') >= 4.5),
            '--plum-soft': f'rgba({rgb(fill)}, .16)', '--slate': slate,
            '--accent': fill, '--accent-hover': hover, '--accent-soft': f'rgba({rgb(fill)}, .14)',
            '--accent-text': link, '--accent2': link, '--on-accent': on_accent,
            '--brand-rgb': rgb(fill), '--slate-rgb': rgb(slate), '--welcome-text': ink,
            '--placeholder': muted, '--welcome-accent': link}

def logo():
    name = text('LOGO', limit=255)
    if not name: return None
    directory = store.database_path().parent.resolve()
    try:
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or not path.is_file(): return None
        with path.open('rb') as source: data = source.read(512 * 1024 + 1)
        if len(data) > 512 * 1024: return None
        if data.startswith(b'\x89PNG\r\n\x1a\n'): return data, 'image/png'
        if data.startswith(b'\xff\xd8\xff'): return data, 'image/jpeg'
        if data.startswith(b'RIFF') and data[8:12] == b'WEBP': return data, 'image/webp'
    except (OSError, ValueError, RuntimeError):
        pass
    return None

def read_brand():
    name = text('NAME')
    asset = logo()
    tokens = theme()
    return {'branded': bool(name), 'name': name or 'Arynwood Grove',
            'tagline': text('TAGLINE', 'The Grove, your community – your choices'),
            'accent': tokens.get('--accent', accent()), 'theme': tokens, 'site_url': url('SITE_URL'), 'site_label': text('SITE_LABEL', 'Website'),
            'shop_url': url('SHOP_URL'), 'shop_label': text('SHOP_LABEL', 'Shop'),
            'logo_url': '/api/brand/logo' if asset else '', '_logo': asset}

@router.get('')
def brand():
    return {key: value for key, value in read_brand().items() if key != '_logo'}

@router.get('/logo')
def brand_logo():
    asset = read_brand()['_logo']
    if not asset: raise HTTPException(404)
    return Response(asset[0], media_type=asset[1])
