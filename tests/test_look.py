"""Look & feel: a Grove's owners choose its name, colours, type, logo and login picture, over the host's settings."""
import io
import os
import random
import unittest
from unittest.mock import patch
import test_hub
import test_files
import test_website
from backend import brand

H = test_hub.H
PNG = b'\x89PNG\r\n\x1a\n' + b'logo' * 10
JPEG = b'\xff\xd8\xff' + b'picture' * 10
LOOK = {'name': 'RogueFest Community', 'tagline': 'Come see what you find.', 'background': '#F4EEE8', 'text': '#091C32',
        'accent': '#E2326F', 'login_background': '#091C32', 'font_heading': 'bold', 'font_body': 'classic', 'corners': 'soft',
        'logo_shape': 'circle', 'site_url': 'https://roguefestfilmfestival.com/', 'site_label': 'Festival website', 'shop_url': '', 'shop_label': ''}


def readable(test, tokens):
    """Every pairing the pages use reads, whatever the colours chosen."""
    for key in ('--text', '--text-muted', '--accent-text', '--success', '--warning', '--danger', '--danger-text'):
        for bg in ('--bg', '--surface', '--surface2'):
            test.assertGreaterEqual(brand.contrast(tokens[key], tokens[bg]), 4.5, (key, bg, tokens[bg]))
    for key in ('--accent', '--accent-hover'):
        test.assertGreaterEqual(brand.contrast(tokens[key], tokens['--on-accent']), 4.5, key)
    for key in ('--border', '--border-strong'):
        test.assertGreaterEqual(brand.contrast(tokens[key], tokens['--surface']), 3, key)
    test.assertGreaterEqual(brand.contrast(tokens['--plum-mid'], '#ffffff'), 4.5)
    for key in ('--login-text', '--login-muted', '--login-accent'):
        for bg in ('--login-bg', '--login-bg2', '--login-bg3'):
            test.assertGreaterEqual(brand.contrast(tokens[key], tokens[bg]), 4.5, (key, bg))


class PaletteTests(unittest.TestCase):
    def test_any_background_light_or_dark_reads(self):
        chooser = random.Random(7)
        backgrounds = ['#ffffff', '#000000', '#f4eee8', '#091c32', '#777777', '#808080', '#2e2e2e', '#ffff00', '#0000ff', '#e2326f']
        backgrounds += ['#%06x' % chooser.randrange(1 << 24) for _ in range(40)]
        for background in backgrounds:
            for ink, source in (('', ''), ('#ffffff', '#ffff00'), ('#000000', '#0000ff'), ('#777777', '#777777')):
                with self.subTest(background=background, ink=ink, source=source):
                    look = brand.host() | {'background': background, 'text': ink, 'accent': source}
                    tokens = brand.theme(look)
                    readable(self, tokens)
                    self.assertEqual(tokens['--scheme'], 'dark' if brand.luminance(background) <= brand.LIGHT else 'light')

    def test_type_corners_and_logo_shape(self):
        plain = brand.host() | {'background': ''}
        self.assertEqual(brand.theme(plain), {})
        tokens = brand.theme(plain | {'font_heading': 'bold', 'font_body': 'classic', 'corners': 'square', 'logo_shape': 'circle'})
        self.assertEqual(tokens['--font-heading'], brand.FONTS['bold'])
        self.assertEqual(tokens['--font-body'], brand.FONTS['classic'])
        self.assertEqual([tokens['--radius'], tokens['--radius-button'], tokens['--logo-radius']], ['2px', '2px', '50%'])


class LookTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member
    upload = test_files.FileTests.upload
    bring_in = test_website.WebsiteTests.bring_in

    def put_image(self, client, kind, data):
        return client.put(f'/api/brand/look/{kind}', headers=H, content=data)

    def test_owners_choose_a_light_look_over_the_hosts_and_can_reset_it(self):
        host, member, sid = self.host_and_member()
        with patch.dict(os.environ, {'GROVE_BRAND_NAME': 'Host Name', 'GROVE_BRAND_SURFACE': '#0f1314', 'GROVE_BRAND_SHOP_URL': 'https://shop.example'}):
            self.assertEqual(host.get('/api/brand/look').json()['look']['name'], 'Host Name')
            # A preview changes nothing.
            preview = host.post('/api/brand/look/preview', headers=H, json=LOOK).json()['theme']
            self.assertEqual([preview['--bg'], preview['--scheme']], ['#f4eee8', 'light'])
            self.assertEqual(host.get('/api/brand').json()['name'], 'Host Name')
            saved = host.put('/api/brand/look', headers=H, json=LOOK)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertTrue(saved.json()['custom'])
            public = member.get('/api/brand').json()
            self.assertEqual([public['name'], public['tagline'], public['site_label'], public['shop_url']],
                             ['RogueFest Community', 'Come see what you find.', 'Festival website', ''])
            tokens = public['theme']
            readable(self, tokens)
            self.assertEqual([tokens['--bg'], tokens['--scheme'], tokens['--font-heading'], tokens['--radius'], tokens['--logo-radius']],
                             ['#f4eee8', 'light', brand.FONTS['bold'], '8px', '50%'])
            # The login page keeps its own dark side, with light words on it.
            self.assertGreater(brand.luminance(tokens['--login-text']), .5)
            log = host.get('/api/admin/activity', params={'limit': 1}).json()['items'][0]
            self.assertEqual(log['action'], 'look_changed')
            self.assertIn('background', log['details']['changed'])
            back = host.delete('/api/brand/look', headers=H).json()
            self.assertEqual([back['custom'], back['look']['name'], back['look']['shop_url']], [False, 'Host Name', 'https://shop.example'])
            self.assertEqual(member.get('/api/brand').json()['theme']['--bg'], '#0f1314')

    def test_only_owners_change_the_look(self):
        host, member, sid = self.host_and_member()
        for method, path in (('get', '/api/brand/look'), ('put', '/api/brand/look'), ('post', '/api/brand/look/preview'), ('delete', '/api/brand/look'),
                             ('put', '/api/brand/look/logo'), ('delete', '/api/brand/look/picture'), ('post', '/api/brand/look/from-site')):
            r = getattr(member, method)(path, headers=H, **({'json': LOOK} if method in ('put', 'post') and 'logo' not in path else {}))
            self.assertEqual(r.status_code, 403, path)
        uid = {p['name']: p['id'] for p in host.get('/api/admin/people').json()}['Member Person']
        host.put(f'/api/admin/people/{uid}/role', headers=H, json={'role': 'manager'}).raise_for_status()
        self.assertEqual(member.put('/api/brand/look', headers=H, json=LOOK).status_code, 403)
        self.assertEqual(member.get('/api/brand').status_code, 200)

    def test_what_an_owner_types_is_checked(self):
        host, member, sid = self.host_and_member()
        for change in ({'background': 'navy'}, {'accent': '#ffffff; color:red'}, {'background': '', 'accent': '#e2326f'},
                       {'site_url': 'javascript:alert(1)'}, {'site_url': 'http://example.com'}, {'name': 'x' * 81}, {'tagline': 'two\nlines'},
                       {'corners': 'wavy'}, {'font_body': 'bold'}):
            r = host.put('/api/brand/look', headers=H, json=LOOK | change)
            self.assertEqual(r.status_code, 422, change)
        self.assertFalse(host.get('/api/brand/look').json()['custom'])

    def test_logo_and_login_picture(self):
        host, member, sid = self.host_and_member()
        visitor = self.enterContext(test_hub.TestClient(test_hub.app))
        r = self.put_image(host, 'logo', PNG)
        self.assertEqual(r.status_code, 200, r.text)
        logo_url = visitor.get('/api/brand').json()['logo_url']
        self.assertRegex(logo_url, r'^/api/brand/logo\?v=[0-9a-f]{16}$')
        served = visitor.get(logo_url)
        self.assertEqual([served.status_code, served.headers['content-type'], served.content], [200, 'image/png', PNG])
        self.assertEqual(self.put_image(host, 'picture', JPEG).status_code, 200)
        host.put('/api/brand/look', headers=H, json=LOOK).raise_for_status()
        public = visitor.get('/api/brand').json()
        self.assertEqual(public['theme']['--login-image'], f'url("{public["picture_url"]}")')
        self.assertEqual(visitor.get(public['picture_url']).content, JPEG)
        # Saving the words and colours keeps the pictures.
        self.assertTrue(visitor.get('/api/brand').json()['logo_url'])
        self.assertEqual(self.put_image(host, 'logo', b'GIF89a not allowed').status_code, 415)
        self.assertEqual(self.put_image(host, 'logo', PNG + b'x' * brand.IMAGES['logo']).status_code, 413)
        files_before = sorted(p.name for p in (brand.store.database_path().parent / 'brand').iterdir())
        self.assertEqual(len(files_before), 2)
        # Removing the logo hides the host's too.
        with patch.dict(os.environ, {'GROVE_BRAND_LOGO': 'brand/' + files_before[0]}):
            host.delete('/api/brand/look/logo', headers=H).raise_for_status()
            self.assertEqual(visitor.get('/api/brand').json()['logo_url'], '')
        host.delete('/api/brand/look', headers=H).raise_for_status()
        self.assertEqual(list((brand.store.database_path().parent / 'brand').iterdir()), [])
        self.assertEqual(visitor.get('/api/brand/picture').status_code, 404)

    def test_the_look_of_a_website_in_files(self):
        host, member, sid = self.host_and_member()
        site = {
            'index.html': b'<!doctype html><meta name="theme-color" content="#091C32"><link rel="stylesheet" href="/styles.css">'
                          b'<header><a class="brand" href="/"><img src="/img/badge.webp" alt="Home"></a></header>'
                          b'<meta property="og:image" content="https://festival.example/img/share.jpg">'
                          b'<main><a href="https://partner.example"><img src="/img/partner-logo.png" alt="Partner logo"></a></main>',
            'styles.css': b':root{--navy:#091C32;--paper:#F4EEE8;--pink:#E2326F;--display:Impact, "Arial Black", sans-serif}'
                          b'body{background:var(--navy);color:var(--paper);font-family:Georgia, serif} h1, h2{font-family:var(--display)}'
                          b'.btn--primary{background:var(--pink);color:#fff} @media print { body { color: #000 } }',
            'img/badge.webp': b'RIFF0000WEBPbadge', 'img/partner-logo.png': PNG, 'img/share.jpg': JPEG,
        }
        self.bring_in(host, sid, site)
        found = host.post('/api/brand/look/from-site', headers=H, json={'space_id': sid, 'folder': 'Website/roguefest-site'}).json()
        self.assertEqual({k: found[k] for k in ('background', 'text', 'accent', 'font_heading', 'font_body')},
                         {'background': '#091c32', 'text': '#f4eee8', 'accent': '#e2326f', 'font_heading': 'bold', 'font_body': 'classic'})
        self.assertEqual([found['logo']['name'], found['picture']['name']], ['badge.webp', 'share.jpg'])
        used = host.post('/api/brand/look/logo/from-file', headers=H, json={'space_id': sid, 'file_id': found['logo']['file_id']})
        self.assertEqual(used.status_code, 200, used.text)
        self.assertEqual(host.get(used.json()['logo_url']).content, site['img/badge.webp'])
        # Only from a space the owner is in, and only a website.
        theirs = member.post('/api/community/spaces', headers=H, json={'name': 'Theirs'}).json()['id']
        self.assertEqual(host.post('/api/brand/look/from-site', headers=H, json={'space_id': theirs, 'folder': 'Website/roguefest-site'}).status_code, 404)
        self.assertEqual(host.post('/api/brand/look/from-site', headers=H, json={'space_id': sid, 'folder': 'Website'}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
