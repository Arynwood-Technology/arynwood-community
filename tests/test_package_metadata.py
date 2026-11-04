"""Grove describes itself the same way everywhere a tool reads it: the members' page package
(frontend/package.json) and every systemd unit's Documentation= link, shown by `systemctl status`."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = 'https://github.com/Arynwood-Technology/arynwood-community/blob/main/deploy/README.md'


class PackageMetadataTests(unittest.TestCase):
    def test_the_package_names_its_license_homepage_and_repository(self):
        package = json.loads((ROOT / 'frontend' / 'package.json').read_text())
        lock = json.loads((ROOT / 'frontend' / 'package-lock.json').read_text())
        self.assertEqual(package['license'], 'AGPL-3.0-only')
        self.assertEqual(lock['packages']['']['license'], package['license'])
        self.assertEqual(package['homepage'], 'https://arynwood.com/community/')
        self.assertIn('Arynwood-Technology/arynwood-community', package['repository']['url'])
        self.assertTrue(package['description'])

    def test_every_unit_links_its_documentation(self):
        units = sorted(p for pattern in ('*.service', '*.timer', '*.path') for p in (ROOT / 'deploy').glob(pattern))
        self.assertGreater(len(units), 10)
        for unit in units:
            with self.subTest(unit=unit.name):
                self.assertIn(f'Documentation={DOCS}', unit.read_text().split('[Service]')[0])


if __name__ == '__main__':
    unittest.main()
