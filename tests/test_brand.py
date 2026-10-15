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
            'tagline': 'The Grove, your community – your choices', 'accent': '#4fd1ab',
            'site_url': '', 'site_label': 'Website', 'shop_url': '', 'shop_label': 'Shop', 'logo_url': ''})
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
