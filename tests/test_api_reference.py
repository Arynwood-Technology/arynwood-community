"""docs/api/ is generated from the Grove (scripts/gen_api_reference.py). These fail when a route changes
without the reference being regenerated, or when a route the Grove serves has no section."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
HTTP_DOCS = ROOT / 'docs' / 'api' / 'http'

# Every (method, path) the Grove answers, found without the generator.
PROBE = r'''
import json, re
from backend.api import app
spec = app.openapi()
found = {(m.upper(), p) for p, item in spec['paths'].items() for m in item}
def walk(routes, prefix=''):
    for r in routes:
        if type(r).__name__ == '_IncludedRouter':
            yield from walk(r.original_router.routes, prefix + r.include_context.prefix)
        else:
            yield prefix, r
for prefix, r in walk(app.routes):
    path = re.sub(r'\{(\w+):\w+\}', r'{\1}', prefix + r.path)
    if 'WebSocket' in type(r).__name__:
        found.add(('WS', path))
    elif not getattr(r, 'include_in_schema', False):
        found |= {(m, path) for m in r.methods}
print(json.dumps(sorted(found)))
'''


def child_env(data):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('GROVE_', 'COMMUNITY_', 'MAIL_'))}
    env['GROVE_DATA_DIR'] = data
    return env


class ApiReferenceTests(unittest.TestCase):
    def test_reference_is_up_to_date(self):
        import fastapi
        pinned = re.search(r'^fastapi==([\d.]+)', (ROOT / 'requirements.txt').read_text(), re.M).group(1)
        self.assertEqual(fastapi.__version__, pinned, 'the OpenAPI document depends on the FastAPI version: '
                         'pip install -r requirements.txt')
        with tempfile.TemporaryDirectory() as data:
            out = subprocess.run([sys.executable, 'scripts/gen_api_reference.py', '--check'], cwd=ROOT, env=child_env(data),
                                 capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stdout[-3000:] + out.stderr[-2000:])

    def test_every_route_the_grove_serves_has_a_section(self):
        with tempfile.TemporaryDirectory() as data:
            out = subprocess.run([sys.executable, '-c', PROBE], cwd=ROOT, env=child_env(data),
                                 capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        served = {tuple(x) for x in json.loads(out.stdout.strip().splitlines()[-1])}
        documented = set()
        for page in HTTP_DOCS.glob('*.md'):
            for methods, path in re.findall(r'^### `([A-Z ]+) (\S+)`$', page.read_text(), re.M):
                documented |= {(m, path) for m in methods.split()}
        self.assertEqual(served - documented, set(), 'routes with no section')
        self.assertEqual(documented - served, set(), "sections for routes the Grove doesn't serve")
        self.assertGreater(len(served), 100)

    def test_host_only_routes_say_so(self):
        # The trust model: everything under these prefixes is the host's alone.
        for page in ('mail.md', 'irc.md', 'grove.md', 'setup.md'):
            rows = re.findall(r'^\| [A-Z, ]+ \| \[`(/\S+)`\]\(#[^)]+\) \| ([^|]+) \|', (HTTP_DOCS / page).read_text(), re.M)
            self.assertTrue(rows, page)
            for path, who in rows:
                self.assertEqual(who.strip(), 'Host', path)


def sample_body(spec, path, method):
    """A body that passes validation, so a check made inside the handler is what answers."""
    op = spec['paths'].get(path, {}).get(method.lower(), {})
    content = op.get('requestBody', {}).get('content', {}).get('application/json')
    if content is None:
        return {} if method in ('POST', 'PUT', 'PATCH') else None
    def value(schema):
        schema = spec['components']['schemas'][schema['$ref'].rsplit('/', 1)[-1]] if '$ref' in schema else schema
        if 'enum' in schema: return schema['enum'][0]
        if 'anyOf' in schema: return value(next(s for s in schema['anyOf'] if s.get('type') != 'null'))
        kind = schema.get('type')
        if kind == 'object': return {k: value(v) for k, v in schema.get('properties', {}).items() if k in schema.get('required', [])}
        if kind == 'array': return []
        if kind == 'integer': return int(schema.get('minimum', 1))
        if kind == 'number': return float(schema.get('minimum', 1))
        if kind == 'boolean': return False
        return 'x' * max(1, int(schema.get('minLength', 1)))
    body = value(content['schema'])
    if path.startswith('/api/community/spaces/{sid}/workspace-setup'):
        from backend.community.workspace_setup import CATALOG
        body['kit'] = next(iter(CATALOG))  # a kit that exists, so the owner check is what answers
    return body


class RolesMatchReferenceTests(unittest.TestCase):
    """A signed-in member who is neither the host nor a Grove owner, manager or webmaster is refused every
    route the reference marks for one of those, and every space-owner route of a space they only belong to."""
    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'GROVE_DATA_DIR': self.data.name})
        self.env.start()
        for name in [k for k in os.environ if k.startswith(('GROVE_', 'COMMUNITY_')) and k != 'GROVE_DATA_DIR']:
            del os.environ[name]
        os.environ['GROVE_HOSTS'] = 'testserver'
    def tearDown(self):
        self.env.stop(); self.data.cleanup()

    def test_a_plain_member_is_refused_what_the_reference_reserves(self):
        from fastapi.testclient import TestClient
        from backend.api import app
        H = {'X-Community-Request': '1'}
        account = lambda email, invite='': {'name': email.split('@')[0], 'email': email, 'password': 'correct horse battery staple',
                                            'space': 'Home', 'invite': invite}
        spec = app.openapi()
        with TestClient(app) as host, TestClient(app) as member:
            self.assertEqual(host.post('/api/auth/signup', headers=H, json=account('host@example.test')).status_code, 200)
            sid = host.get('/api/community/spaces').json()[0]['id']
            token = host.post(f'/api/community/spaces/{sid}/invites', headers=H).json()['token']
            self.assertEqual(member.post('/api/auth/signup', headers=H, json=account('member@example.test', token)).status_code, 200)
            checked = 0
            for page in HTTP_DOCS.glob('*.md'):
                for methods, path, who in re.findall(r'^\| ([A-Z, ]+) \| \[`(/\S*)`\]\(#[^)]+\) \| ([^|]+) \|', page.read_text(), re.M):
                    if who.strip() not in ('Host', 'Grove owner', 'Grove manager', 'Webmaster', 'Space owner'):
                        continue
                    url = re.sub(r'\{(\w+)\}', lambda m: sid if m.group(1) == 'sid' else 'x', path)
                    for method in methods.split(', '):
                        if method == 'WS':
                            continue
                        r = member.request(method, url, headers=H, json=sample_body(spec, path, method))
                        self.assertEqual(r.status_code, 403, f'{method} {path} ({who.strip()}): {r.status_code} {r.text[:200]}')
                        checked += 1
            self.assertGreater(checked, 40)


if __name__ == '__main__':
    unittest.main()
