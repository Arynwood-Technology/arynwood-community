"""Public Grove identity. Keep its source behind read_brand for future asset management."""
import re
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
    return {'branded': bool(name), 'name': name or 'Arynwood Grove',
            'tagline': text('TAGLINE', 'The Grove, your community – your choices'),
            'accent': accent(), 'site_url': url('SITE_URL'), 'site_label': text('SITE_LABEL', 'Website'),
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
