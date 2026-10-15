"""The wish lamp: anyone asks for something in the Grove; it is kept, and emailed when it can be."""
import email
import os
import smtplib
import unittest
from unittest.mock import patch
import test_hub
from backend.routers import mail

H = test_hub.H
MAIL = {'GROVE_WISH_EMAIL': 'builder@example.test', 'GROVE_PUBLIC_URL': 'https://grove.example.test',
        'MAIL_SMTP_HOST': 'smtp.example.test', 'MAIL_SMTP_USER': 'grove@example.test', 'MAIL_SMTP_PASS': 'p'}


class WishTests(unittest.TestCase):
    setUp = test_hub.HubTests.setUp
    tearDown = test_hub.HubTests.tearDown
    signup = test_hub.HubTests.signup
    invite = test_hub.HubTests.invite
    host_and_member = test_hub.HubTests.host_and_member

    def wish(self, client, body='A shared folder for festival posters', **extra):
        return client.post('/api/wishes', headers=H, json={'body': body, **extra})

    def test_a_wish_is_kept_and_emailed_to_the_builder(self):
        host, member, sid = self.host_and_member()
        with patch.dict(os.environ, MAIL), patch.object(mail.smtplib, 'SMTP') as smtp:
            r = self.wish(member, page='calendar', space_id=sid)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(r.json()['emailed'])
        sender, recipients, raw = smtp.return_value.__enter__.return_value.sendmail.call_args.args
        sent = email.message_from_string(raw)
        self.assertEqual([sender, recipients], ['grove@example.test', ['builder@example.test']])
        self.assertEqual([sent['Subject'], sent['Reply-To']], ['Grove wish from Member Person (grove.example.test)', 'member@example.test'])
        text = sent.get_payload()[0].get_payload(decode=True).decode()
        for words in ('A shared folder for festival posters', 'page: calendar · space: Our home', 'Grove: https://grove.example.test'):
            self.assertIn(words, text)
        kept = host.get('/api/admin/wishes').json()
        self.assertEqual([(w['author_name'], w['space_name'], w['delivery']) for w in kept], [('Member Person', 'Our home', 'sent')])
        self.assertEqual(host.get('/api/admin/activity', params={'limit': 1}).json()['items'][0]['action'], 'wish_made')

    def test_without_mail_a_wish_is_kept_for_the_owners(self):
        host, member, sid = self.host_and_member()
        with patch.dict(os.environ, {**MAIL, 'MAIL_SMTP_HOST': ''}), patch.object(mail.smtplib, 'SMTP') as smtp:
            self.assertFalse(self.wish(member).json()['emailed'])
        with patch.dict(os.environ, {**MAIL, 'GROVE_WISH_EMAIL': 'not an address'}), patch.object(mail.smtplib, 'SMTP') as smtp:
            self.assertFalse(self.wish(member).json()['emailed'])
        smtp.assert_not_called()
        self.assertEqual([w['delivery'] for w in host.get('/api/admin/wishes').json()], ['kept', 'kept'])

    def test_a_wish_that_cannot_be_sent_is_still_kept(self):
        host, member, sid = self.host_and_member()
        with patch.dict(os.environ, MAIL), patch.object(mail.smtplib, 'SMTP', side_effect=smtplib.SMTPConnectError(421, 'busy')):
            self.assertEqual(self.wish(member).status_code, 201)
        self.assertEqual(host.get('/api/admin/wishes').json()[0]['delivery'], 'failed')

    def test_only_owners_and_managers_read_wishes(self):
        host, member, sid = self.host_and_member()
        other = host.post('/api/community/spaces', headers=H, json={'name': 'Owners only'}).json()
        # A space the wisher is not in is not named.
        self.wish(member, space_id=other['id'])
        self.assertEqual(host.get('/api/admin/wishes').json()[0]['space_name'], '')
        self.assertEqual(member.get('/api/admin/wishes').status_code, 403)
        self.assertEqual(self.wish(member, body='   ').status_code, 422)
        self.assertEqual(self.wish(member, page='../etc').status_code, 422)
        self.assertEqual(self.wish(member, body='x' * 4001).status_code, 422)

    def test_one_person_makes_only_a_few_wishes_at_a_time(self):
        host, member, sid = self.host_and_member()
        for n in range(10):
            self.assertEqual(self.wish(member, body=f'Wish {n}').status_code, 201)
        self.assertEqual(self.wish(member).status_code, 429)
        self.assertEqual(self.wish(host).status_code, 201)


if __name__ == '__main__':
    unittest.main()
