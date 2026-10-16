"""Public branding validation, without an account or a database migration."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_hub
from fastapi.testclient import TestClient
from backend.api import app
from backend import brand

class BrandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'GROVE_DATA_DIR': self.directory.name}, clear=True)
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.directory.cleanup()

    def test_public_defaults(self):
        response = self.client.get('/api/brand')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'branded': False, 'name': 'Arynwood Grove',
            'tagline': 'The Grove, your community – your choices', 'accent': '#4fd1ab', 'theme': {},
            'site_url': '', 'site_label': 'Website', 'shop_url': '', 'shop_label': 'Shop', 'logo_url': '', 'picture_url': ''})
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get('/api/brand/logo').status_code, 404)

    def test_text_settings_and_fallbacks(self):
        defaults = brand.read_brand()
        for field, key in [('name','NAME'), ('tagline','TAGLINE'), ('site_label','SITE_LABEL'), ('shop_label','SHOP_LABEL')]:
            with self.subTest(field=field):
                with patch.dict(os.environ, {'GROVE_BRAND_'+key: '  Festival  '}):
                    self.assertEqual(brand.read_brand()[field], 'Festival')
                for invalid in ('', ' ', 'x'*161, 'bad\x01text', 'bad\ntext'):
                    with patch.dict(os.environ, {'GROVE_BRAND_'+key: invalid}):
                        self.assertEqual(brand.read_brand()[field], defaults[field])
        with patch.dict(os.environ, {'GROVE_BRAND_NAME':'Festival'}):
            self.assertTrue(brand.read_brand()['branded'])

    def test_url_validation_for_both_links(self):
        for key in ('SITE', 'SHOP'):
            for value in ('https://festival.example/path?x=1', 'http://localhost:8080', 'http://127.0.0.1:8080', 'http://[::1]:8080'):
                with self.subTest(key=key, value=value), patch.dict(os.environ, {'GROVE_BRAND_'+key+'_URL':value}):
                    self.assertEqual(brand.read_brand()[key.lower()+'_url'], value)
            for value in ('http://festival.example', '//festival.example', 'javascript:alert(1)', 'https://', 'https://user:pass@festival.example', 'https://festival.example:bad', 'http://localhost.evil', 'https://bad host', 'https://bad\\host', 'https://[bad'):
                with self.subTest(key=key, value=value), patch.dict(os.environ, {'GROVE_BRAND_'+key+'_URL':value}):
                    self.assertEqual(brand.read_brand()[key.lower()+'_url'], '')

    def test_accent_contrast_and_syntax(self):
        for value in ('#FFFFFF', '#aaffcc'):
            with patch.dict(os.environ, {'GROVE_BRAND_ACCENT':value}):
                self.assertEqual(brand.read_brand()['accent'], value.lower())
        for value in ('#000000', '#777777', '#fff', 'red', '#ggffff', '#ffffff; color:red'):
            with patch.dict(os.environ, {'GROVE_BRAND_ACCENT':value}):
                self.assertEqual(brand.read_brand()['accent'], brand.DEFAULT_ACCENT)

    def test_logo_magic_size_and_response(self):
        path = Path(self.directory.name) / 'logo.bin'
        with patch.dict(os.environ, {'GROVE_BRAND_LOGO':'logo.bin'}):
            for signature, mime in [(b'\x89PNG\r\n\x1a\n','image/png'), (b'\xff\xd8\xff','image/jpeg'), (b'RIFF1234WEBP','image/webp')]:
                data = signature + b'0' * (512 * 1024 - len(signature))
                path.write_bytes(data)
                self.assertEqual(brand.read_brand()['logo_url'], '/api/brand/logo')
                response = self.client.get('/api/brand/logo')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['content-type'], mime)
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                self.assertEqual(response.content, data)
                path.write_bytes(data + b'0')
                self.assertEqual(self.client.get('/api/brand/logo').status_code, 404)
            for data in (b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'GIF89a', b'RIFF1234WAVE', b''):
                path.write_bytes(data)
                self.assertEqual(brand.read_brand()['logo_url'], '')
                self.assertEqual(self.client.get('/api/brand/logo').status_code, 404)

    def test_logo_cannot_escape_data_directory(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'logo.png'
            target.write_bytes(b'\x89PNG\r\n\x1a\n')
            link = Path(self.directory.name) / 'link.png'
            link.symlink_to(target)
            for name in (str(target), '../'+Path(outside).name+'/logo.png', 'link.png', 'missing.png', '.'):
                with patch.dict(os.environ, {'GROVE_BRAND_LOGO':name}):
                    self.assertEqual(brand.read_brand()['logo_url'], '')
                    self.assertEqual(self.client.get('/api/brand/logo').status_code, 404)

    def test_theme_validation_and_legacy_behaviour(self):
        for surface in ('', 'navy', '#fff', '#zzzzzz', '#ffffff', '#808080'):
            with self.subTest(surface=surface), patch.dict(os.environ, {'GROVE_BRAND_SURFACE':surface, 'GROVE_BRAND_ACCENT':'#E2326F'}):
                result = self.client.get('/api/brand').json()
                self.assertEqual(result['theme'], {})
                self.assertEqual(result['accent'], brand.DEFAULT_ACCENT)
        with patch.dict(os.environ, {'GROVE_BRAND_TEXT':'#F4EEE8', 'GROVE_BRAND_ACCENT':'#aaffcc'}):
            self.assertEqual(brand.read_brand()['theme'], {})
            self.assertEqual(brand.read_brand()['accent'], '#aaffcc')
        with patch.dict(os.environ, {'GROVE_BRAND_SURFACE':'#091C32'}):
            defaults = brand.read_brand()['theme']
            for value in ('red', '#fff', '#000000', '#777777', '#ffffff; color:red'):
                with self.subTest(text=value), patch.dict(os.environ, {'GROVE_BRAND_TEXT':value}):
                    self.assertEqual(brand.read_brand()['theme'], defaults)
            for value in ('red', '#fff', '#ggffff'):
                with patch.dict(os.environ, {'GROVE_BRAND_ACCENT':value}):
                    self.assertEqual(brand.read_brand()['theme'], defaults)

    def test_theme_contrast_pairs_for_roguefest_and_default(self):
        palettes = [('#091C32', '#F4EEE8', '#E2326F'), ('#0f1314', '#f4f8f6', '#4fd1ab')]
        expected = {'bg','surface','surface2','border','border-strong','text','text-muted',
                    'plum','plum-mid','plum-soft','slate','accent','accent-hover','accent-soft',
                    'accent-text','accent2','on-accent'}
        for surface, ink, accent in palettes:
            with self.subTest(surface=surface), patch.dict(os.environ, {
                    'GROVE_BRAND_SURFACE':surface, 'GROVE_BRAND_TEXT':ink, 'GROVE_BRAND_ACCENT':accent}):
                result = self.client.get('/api/brand').json()
                tokens = result['theme']
                self.assertTrue({'--'+key for key in expected} <= tokens.keys())
                self.assertEqual(tokens['--bg'], surface.lower())
                self.assertEqual(result['accent'], tokens['--accent'])
                for key in ('--accent', '--accent-hover'):
                    self.assertGreaterEqual(brand.contrast(tokens[key], tokens['--on-accent']), 4.5)
                self.assertIn(tokens['--on-accent'], ('#ffffff', tokens['--bg']))
                for key in ('--accent-text', '--accent2', '--text', '--text-muted'):
                    for bg in ('--bg', '--surface', '--surface2'):
                        self.assertGreaterEqual(brand.contrast(tokens[key], tokens[bg]), 4.5, (key, bg))
                for key in ('--border', '--border-strong'):
                    self.assertGreaterEqual(brand.contrast(tokens[key], tokens['--surface']), 3)
                self.assertGreaterEqual(brand.contrast(tokens['--plum-mid'], '#ffffff'), 4.5)
                self.assertEqual(tokens['--accent-text'], tokens['--accent2'])

    def test_accent_keeps_hue_and_is_nearest_passing_lightness(self):
        with patch.dict(os.environ, {'GROVE_BRAND_SURFACE':'#091C32', 'GROVE_BRAND_TEXT':'#F4EEE8', 'GROVE_BRAND_ACCENT':'#E2326F'}):
            tokens = brand.read_brand()['theme']
            source = '#e2326f'
            for key in ('--accent', '--accent-text'):
                def passes(value):
                    if key == '--accent': return max(brand.contrast(value, '#ffffff'), brand.contrast(value, tokens['--bg'])) >= 4.5
                    return all(brand.contrast(value, tokens[bg]) >= 4.5 for bg in ('--bg','--surface','--surface2'))
                hue, lightness, saturation = brand.hls(source)
                derived = brand.hls(tokens[key])
                self.assertAlmostEqual(hue, derived[0], delta=.002)
                self.assertAlmostEqual(saturation, derived[2], delta=.01)
                self.assertTrue(passes(tokens[key]))
                distance = abs(derived[1] - lightness)
                for step in range(1, max(1, int(distance * 1000) - 1)):
                    for direction in (-1, 1):
                        self.assertFalse(passes(brand.with_lightness(source, lightness + direction * step / 1000)))

    def test_contrast_reference_and_extreme_accents(self):
        self.assertEqual(brand.contrast('#000000', '#ffffff'), 21)
        self.assertAlmostEqual(brand.contrast('#ffffff', '#777777'), 4.478, places=3)
        for surface in ('#000000', '#595959', '#350030', '#5b5b00'):
            for source in ('#000000', '#ffffff', '#777777', '#ff0000', '#00ff00', '#0000ff'):
                with self.subTest(surface=surface, source=source), patch.dict(os.environ, {
                        'GROVE_BRAND_SURFACE':surface, 'GROVE_BRAND_ACCENT':source}):
                    tokens = brand.read_brand()['theme']
                    self.assertGreaterEqual(brand.contrast(tokens['--accent'], tokens['--on-accent']), 4.5)
                    self.assertGreaterEqual(brand.contrast(tokens['--accent-text'], tokens['--surface2']), 4.5)
                    self.assertGreaterEqual(brand.contrast(tokens['--text-muted'], tokens['--surface2']), 4.5)
