"""The release workflow publishes the build attestation as a release file, after checking every published file
against it. Reads .github/workflows/release.yml; nothing here runs a release."""
import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / '.github' / 'workflows' / 'release.yml'


class ReleaseProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()

    def test_the_provenance_file_is_the_attestation_bundle(self):
        self.assertIn('id: attest', self.text)
        self.assertIn("BUNDLE: '${{ steps.attest.outputs.bundle-path }}'", self.text)
        self.assertIn('provenance="release/arynwood-grove-${GITHUB_REF_NAME#v}_provenance.intoto.jsonl"', self.text)

    def test_every_published_file_is_checked_against_it_before_publishing(self):
        before, publish = self.text.split('- name: Publish', 1)
        self.assertRegex(before, r'for f in release/install\.sh release/arynwood-grove\*\.tar\.gz; do\n'
                                 r'\s+gh attestation verify "\$f" --bundle "\$provenance".*\n.*--source-ref "\$GITHUB_REF"')
        self.assertIn('release/arynwood-grove-*_provenance.intoto.jsonl', publish)


if __name__ == '__main__':
    unittest.main()
