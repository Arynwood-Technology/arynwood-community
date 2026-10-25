"""The installer, the updater and the upgrade script install a release only after checking it against its
SHA-256 checksum, and download it over HTTPS only. Runs the scripts' own shell functions against real files
and a local HTTPS server; nothing here needs root or the network."""
import hashlib
import http.server
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [ROOT / 'deploy' / name for name in ('install.sh', 'arynwood-grove', 'upgrade-from-community.sh')]
START, END = '# --- Release delivery', '# --- end of release delivery'


def block(path):
    text = path.read_text()
    return text[text.index(START):text.index(END) + len(END)]


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


class ReleaseDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.base = Path(cls.dir.name)
        (cls.base / 'delivery.sh').write_text(block(SCRIPTS[0]) + '\n')
        # A release and its checksum, as scripts/package.sh writes them.
        cls.release = cls.base / 'www' / 'arynwood-grove-9.9.9.tar.gz'
        cls.release.parent.mkdir()
        cls.release.write_bytes(os.urandom(4096))
        cls.digest = hashlib.sha256(cls.release.read_bytes()).hexdigest()
        cls.write_sums(cls.release, f'{cls.digest}  {cls.release.name}\n')
        # The same release with one byte changed after its checksum was published.
        cls.tampered = cls.base / 'www' / 'tampered' / cls.release.name
        cls.tampered.parent.mkdir()
        data = bytearray(cls.release.read_bytes()); data[100] ^= 1
        cls.tampered.write_bytes(bytes(data))
        cls.write_sums(cls.tampered, f'{cls.digest}  {cls.release.name}\n')
        # The same release with no checksum published.
        cls.unsummed = cls.base / 'www' / 'nosum' / cls.release.name
        cls.unsummed.parent.mkdir()
        shutil.copy(cls.release, cls.unsummed)
        cls.https = cls.serve()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.plain):
            server.shutdown(); server.server_close()
        cls.dir.cleanup()

    @staticmethod
    def write_sums(path, text):
        Path(str(path) + '.sha256').write_text(text)

    @classmethod
    def serve(cls):
        """A local HTTPS server for the files under www/, with its own certificate, and a plain HTTP one for the
        same files; /redirect/* on the HTTPS server sends the client to the plain one, the downgrade an attacker
        on the path would try."""
        key, cert = cls.base / 'key.pem', cls.base / 'cert.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', cert, '-days', '1',
                        '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1'], check=True, capture_output=True)
        www = cls.base / 'www'
        # The redirects it makes: only to the two files the tests ask for, never built from the request.
        names = (cls.release.name, cls.release.name + '.sha256')
        redirects = {f'/redirect/{name}': name for name in names}

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw): super().__init__(*a, directory=str(www), **kw)
            def log_message(self, *a): pass
            def do_GET(self):
                if self.path.startswith('/redirect/'):
                    target = redirects.get(self.path)
                    if target is None:
                        self.send_error(404); return
                    self.send_response(302)
                    self.send_header('Location', f'http://127.0.0.1:{cls.plain.server_address[1]}/{target}')
                    self.end_headers()
                    return
                super().do_GET()

        cls.plain = Server(('127.0.0.1', 0), Handler)
        threading.Thread(target=cls.plain.serve_forever, daemon=True).start()
        cls.server = Server(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, key)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.cert = cert
        return f'https://127.0.0.1:{cls.server.server_address[1]}'

    def run_shell(self, command):
        env = {'PATH': os.environ['PATH'], 'CURL_CA_BUNDLE': str(self.cert), 'HOME': self.dir.name}
        return subprocess.run(['bash', '-c', f'set -u; source {self.base / "delivery.sh"}; {command}'], env=env,
                              capture_output=True, text=True, timeout=60)

    def fresh(self):
        out = Path(tempfile.mkdtemp(dir=self.dir.name))
        return out

    # verify_release ------------------------------------------------------------------------------
    def test_the_three_scripts_carry_the_same_checks(self):
        copies = {path.name: block(path) for path in SCRIPTS}
        self.assertEqual(len(set(copies.values())), 1, list(copies))

    def test_a_release_matching_its_checksum_passes(self):
        r = self.run_shell(f'verify_release {self.release}')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_changed_release_is_refused(self):
        r = self.run_shell(f'verify_release {self.tampered}')
        self.assertEqual(r.returncode, 1)
        self.assertIn('does not match its checksum', r.stderr)

    def test_a_release_without_a_checksum_is_refused(self):
        for sums in (None, ''):
            folder = self.fresh(); copy = folder / self.release.name
            shutil.copy(self.release, copy)
            if sums is not None: self.write_sums(copy, sums)
            r = self.run_shell(f'verify_release {copy}')
            self.assertEqual(r.returncode, 1)
            self.assertIn('No checksum for', r.stderr)

    def test_a_malformed_or_misnamed_checksum_is_refused(self):
        cases = {f'{self.digest[:63]}  {self.release.name}': 'not a SHA-256 checksum file',
                 f'{self.digest.upper()}  {self.release.name}': 'not a SHA-256 checksum file',
                 f'{self.digest}  {self.release.name}\n{self.digest}  other.tar.gz': 'not a SHA-256 checksum file',
                 f'{self.digest}  ../{self.release.name}': 'not a SHA-256 checksum file',
                 f'{self.digest}  arynwood-grove-1.0.0.tar.gz': 'is the checksum of arynwood-grove-1.0.0.tar.gz'}
        for sums, message in cases.items():
            folder = self.fresh(); copy = folder / self.release.name
            shutil.copy(self.release, copy); self.write_sums(copy, sums + '\n')
            r = self.run_shell(f'verify_release {copy}')
            self.assertEqual(r.returncode, 1, sums)
            self.assertIn(message, r.stderr, sums)

    def test_sha256sum_binary_mode_marker_is_accepted(self):
        folder = self.fresh(); copy = folder / self.release.name
        shutil.copy(self.release, copy); self.write_sums(copy, f'{self.digest} *{self.release.name}\n')
        self.assertEqual(self.run_shell(f'verify_release {copy}').returncode, 0)

    # fetch_release -------------------------------------------------------------------------------
    def test_download_over_https_with_its_checksum(self):
        folder = self.fresh()
        r = self.run_shell(f'fetch_release {self.https} {self.release.name} {folder}')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((folder / self.release.name).read_bytes(), self.release.read_bytes())

    def test_a_changed_download_is_refused(self):
        r = self.run_shell(f'fetch_release {self.https}/tampered {self.release.name} {self.fresh()}')
        self.assertEqual(r.returncode, 1)
        self.assertIn('does not match its checksum', r.stderr)

    def test_a_download_without_a_published_checksum_is_refused(self):
        r = self.run_shell(f'fetch_release {self.https}/nosum {self.release.name} {self.fresh()}')
        self.assertEqual(r.returncode, 1)
        self.assertIn('Could not download the checksum', r.stderr)

    def test_plain_http_is_refused_before_any_download(self):
        folder = self.fresh()
        r = self.run_shell(f'fetch_release http://127.0.0.1:9/www {self.release.name} {folder}')
        self.assertEqual(r.returncode, 1)
        self.assertIn('over HTTPS only', r.stderr)
        self.assertEqual(list(folder.iterdir()), [])

    def test_a_redirect_to_plain_http_is_not_followed(self):
        r = self.run_shell(f'fetch_release {self.https}/redirect {self.release.name} {self.fresh()}')
        self.assertEqual(r.returncode, 1)
        self.assertIn('Could not download', r.stderr)

    def test_an_untrusted_certificate_is_refused(self):
        env = {'PATH': os.environ['PATH'], 'HOME': self.dir.name}  # no CURL_CA_BUNDLE: the system's trust only
        r = subprocess.run(['bash', '-c', f'source {self.base / "delivery.sh"}; fetch_release {self.https} {self.release.name} {self.fresh()}'],
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)

    # where the checks sit --------------------------------------------------------------------------
    def test_every_download_goes_through_the_checks(self):
        for path in SCRIPTS:
            outside = path.read_text().replace(block(path), '')
            self.assertNotRegex(outside, r'curl[^\n]*\s-o\s', f'{path.name} downloads outside fetch_release')
            self.assertNotIn('sha256sum -c', outside, path.name)

    def test_the_installer_checks_the_release_before_it_changes_the_server(self):
        lines = (ROOT / 'deploy' / 'install.sh').read_text().split('\n')
        first = lambda pattern: next(i for i, line in enumerate(lines) if re.search(pattern, line))
        checked = max(first(r'fetch_release "\$base"'), first(r'verify_release "\$FROM"'))
        for change in (r'apt-get install -y -qq "\$\{packages', r'useradd ', r'install -d -m 0755 "\$PREFIX"', r'python3 -m venv'):
            self.assertLess(checked, first(change), change)

    def test_the_updater_checks_a_release_before_running_its_installer(self):
        text = (ROOT / 'deploy' / 'arynwood-grove').read_text()
        update = text[text.index('\n  update)'):text.index('\n  rollback)')]
        self.assertLess(update.index('verify_release "$from"'), update.index('tar -xzf "$from"'))
        self.assertLess(update.index('fetch_release "$base"'), update.index('tar -xzf "$from"'))

    def test_the_upgrade_script_checks_its_release_before_unpacking_it(self):
        text = (ROOT / 'deploy' / 'upgrade-from-community.sh').read_text().replace(block(SCRIPTS[2]), '')
        self.assertLess(text.index('verify_release "$FROM"'), text.index('tar -xzf "$FROM"'))


if __name__ == '__main__':
    unittest.main()
