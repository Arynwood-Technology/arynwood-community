"""Grove TLS key policy tests use public certificate metadata fixtures only."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (ROOT / 'deploy/install.sh', ROOT / 'deploy/arynwood-grove')
START = '# BEGIN Grove TLS public-key policy'
END = '# END Grove TLS public-key policy'


def policy_block(script):
    text = script.read_text()
    start = text.index(START)
    end = text.index(END, start) + len(END)
    return text[start:end]


class TLSKeyPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policies = [policy_block(script) for script in SCRIPTS]

    def check_public_key(self, policy, metadata, expected, openssl_exit=0):
        with tempfile.TemporaryDirectory() as directory:
            fake_bin = Path(directory)
            openssl = fake_bin / 'openssl'
            openssl.write_text(
                '#!/bin/sh\n'
                'test "${TLS_TEST_OPENSSL_EXIT:-0}" = 0 || exit 1\n'
                'printf "%s\\n" "$TLS_TEST_OPENSSL_TEXT"\n'
            )
            openssl.chmod(0o755)
            env = os.environ.copy()
            env['PATH'] = f'{fake_bin}:{env["PATH"]}'
            env['TLS_TEST_OPENSSL_TEXT'] = metadata
            env['TLS_TEST_OPENSSL_EXIT'] = str(openssl_exit)
            result = subprocess.run(
                ['bash', '-c', policy + '\ntls_certificate_key_is_strong public-cert.pem'],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode == 0, expected, result.stderr)
            self.assertEqual(result.stdout, '')

    def check_certificate(self, policy, metadata, expected, certificate_exists, required, openssl_exit=0):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            fake_bin = temp / 'bin'
            fake_bin.mkdir()
            openssl = fake_bin / 'openssl'
            openssl.write_text(
                '#!/bin/sh\n'
                'test "${TLS_TEST_OPENSSL_EXIT:-0}" = 0 || exit 1\n'
                'printf "%s\\n" "$TLS_TEST_OPENSSL_TEXT"\n'
            )
            openssl.chmod(0o755)
            certificate = temp / 'cert.pem'
            if certificate_exists:
                certificate.write_text('public certificate test fixture\n')
            env = os.environ.copy()
            env.update({
                'PATH': f'{fake_bin}:{env["PATH"]}',
                'TLS_TEST_OPENSSL_TEXT': metadata,
                'TLS_TEST_OPENSSL_EXIT': str(openssl_exit),
                'TEST_CERTIFICATE': str(certificate),
            })
            command = (
                policy
                + f'\ntls_certificate_key_check "$TEST_CERTIFICATE" example.test {required}'
            )
            result = subprocess.run(['bash', '-c', command], env=env, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode == 0, expected, result.stderr)

    def test_policy_is_the_same_in_standalone_installer_and_grove_command(self):
        self.assertEqual(self.policies[0], self.policies[1])
        self.assertIn('openssl x509 -in "$certificate" -noout -text', self.policies[0])
        self.assertNotIn('openssl pkey', self.policies[0])

    def test_rsa_minimum_is_2048_bits(self):
        for policy in self.policies:
            with self.subTest(bits=2048):
                self.check_public_key(policy, 'Public Key Algorithm: rsaEncryption\nPublic-Key: (2048 bit)', True)
            with self.subTest(bits=1024):
                self.check_public_key(policy, 'Public Key Algorithm: rsaEncryption\nPublic-Key: (1024 bit)', False)

    def test_ecdsa_requires_at_least_nist_p256(self):
        for policy in self.policies:
            with self.subTest(curve='prime256v1'):
                self.check_public_key(
                    policy,
                    'Public Key Algorithm: id-ecPublicKey\nPublic-Key: (256 bit)\nASN1 OID: prime256v1',
                    True,
                )
            with self.subTest(curve='secp224r1'):
                self.check_public_key(
                    policy,
                    'Public Key Algorithm: id-ecPublicKey\nPublic-Key: (224 bit)\nASN1 OID: secp224r1',
                    False,
                )

    def test_unknown_key_types_and_unreadable_certificates_are_refused(self):
        for policy in self.policies:
            with self.subTest(key_type='ED25519'):
                self.check_public_key(policy, 'Public Key Algorithm: ED25519\nPublic-Key: (256 bit)', False)
            with self.subTest(certificate='unreadable'):
                self.check_public_key(policy, '', False, openssl_exit=1)

    def test_missing_or_weak_certificates_are_refused_when_https_requires_one(self):
        strong_rsa = 'Public Key Algorithm: rsaEncryption\nPublic-Key: (2048 bit)'
        weak_rsa = 'Public Key Algorithm: rsaEncryption\nPublic-Key: (1024 bit)'
        for policy in self.policies:
            with self.subTest(case='optional new cert'):
                self.check_certificate(policy, '', True, certificate_exists=False, required=0)
            with self.subTest(case='required cert absent'):
                self.check_certificate(policy, '', False, certificate_exists=False, required=1)
            with self.subTest(case='strong cert present'):
                self.check_certificate(policy, strong_rsa, True, certificate_exists=True, required=1)
            with self.subTest(case='weak cert present'):
                self.check_certificate(policy, weak_rsa, False, certificate_exists=True, required=1)

    def test_certbot_managed_https_pins_new_certificates_to_ecdsa_p256(self):
        for script in SCRIPTS:
            with self.subTest(script=script.name):
                text = script.read_text()
                self.assertIn('--key-type ecdsa --elliptic-curve secp256r1', text)
                self.assertIn('tls_certificate_key_check "$cert"', text)

    def test_offsite_sftp_passes_minimum_rsa_and_key_type_policy_to_openssh(self):
        text = (ROOT / 'deploy/arynwood-grove').read_text()
        start = text.index('offsite_restic() {')
        end = text.index('\n}', start) + 2
        function = text[start:end]
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            fake_bin = temp / 'bin'
            fake_bin.mkdir()
            restic = fake_bin / 'restic'
            restic.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            restic.chmod(0o755)
            env_file = temp / 'offsite.env'
            env_file.write_text('RESTIC_REPOSITORY=sftp:backup@example.test:/repo\n')
            env = os.environ.copy()
            env.update({
                'PATH': f'{fake_bin}:{env["PATH"]}',
                'TEST_OFFSITE_ENV': str(env_file),
                'TEST_OFFSITE_STATE': str(temp / 'state'),
            })
            command = (
                'OFFSITE_ENV="$TEST_OFFSITE_ENV"; '
                'OFFSITE_STATE="$TEST_OFFSITE_STATE"; '
                + function
                + '\noffsite_restic backup'
            )
            result = subprocess.run(['bash', '-c', command], env=env, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('RequiredRSASize=2048', result.stdout)
            self.assertIn('ecdsa-sha2-nistp256', result.stdout)
            self.assertIn('ssh-ed25519', result.stdout)

    def test_offsite_sftp_rejects_custom_command_that_could_skip_policy(self):
        text = (ROOT / 'deploy/arynwood-grove').read_text()
        start = text.index('offsite_restic() {')
        end = text.index('\n}', start) + 2
        function = text[start:end]
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            env_file = temp / 'offsite.env'
            env_file.write_text(
                'RESTIC_REPOSITORY=sftp:backup@example.test:/repo\n'
                'RESTIC_SFTP_COMMAND=custom-ssh\n'
            )
            env = os.environ.copy()
            env.update({'TEST_OFFSITE_ENV': str(env_file), 'TEST_OFFSITE_STATE': str(temp / 'state')})
            command = (
                'OFFSITE_ENV="$TEST_OFFSITE_ENV"; '
                'OFFSITE_STATE="$TEST_OFFSITE_STATE"; '
                + function
                + '\noffsite_restic backup'
            )
            result = subprocess.run(['bash', '-c', command], env=env, capture_output=True, text=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Custom SFTP commands are refused', result.stderr)


if __name__ == '__main__':
    unittest.main()
