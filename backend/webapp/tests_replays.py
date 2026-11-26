# SPDX-License-Identifier: AGPL-3.0-only
"""Replay download, current session scope and the archive boundary."""
import gzip
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from backend.match_orchestrator import replays as P
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T
from .models import Identity, OrganizerAssignment
from .tests import FeatureAPI


class ReplayAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        FeatureAPI.setUpTestData.__func__(cls)

    def setUp(self):
        fixture = FeatureAPI()
        fixture.a = self.a
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.rt = fixture.rt
        self.match = self.rt.flow.store.snapshot()['series'][fixture.sid]['games'][0]['match_id']
        self.url = self.replay_url(self.match)
        self.bytes = gzip.compress(b'Local test replay for the official fixture game.' * 300)
        self.source = fixture.root / 'fixture-output.bc26'
        self.source.write_bytes(self.bytes)
        P.register_replay(self.rt.vault, 'cup', self.match, self.source, None)
        self.vault_file = self.rt.vault.root / 'cup' / (self.match + '.bc26')
        self.staff = R.Actor('staff', 'admin')

    def replay_url(self, match_id):
        return f'/api/v1/matches/{match_id}/replay/'

    def reader(self, user):
        client = Client()
        if user is not None:
            client.force_login(user)
        return client

    def read_download(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.streaming)
        data = b''.join(response.streaming_content)  # Django's test iterator closes the response.
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        self.assertEqual(response['Content-Disposition'], f'attachment; filename="{self.match}.bc26"')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(int(response['Content-Length']), len(self.bytes))
        self.assertTrue(response['X-Request-ID'].startswith('req_'))
        self.assertNotIn('Content-Encoding', response)
        return data

    def error(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertFalse(response.streaming)
        error = response.json()['error']
        self.assertEqual(error.pop('request_id'), response['X-Request-ID'])
        self.assertEqual(error['code'], code)
        self.assertEqual(error['details'], {})
        self.assertNotIn(str(self.rt.vault.root), response.content.decode())
        return error

    def test_scoped_roles_stream_exact_bytes_from_current_vault(self):
        for user in (self.a, self.b, self.org, self.admin):
            with self.subTest(user=user.username):
                client = self.reader(user)
                self.assertEqual(self.read_download(client.get(self.url, HTTP_ACCEPT='application/octet-stream')), self.bytes)
        live = self.reader(self.a).get('/api/v1/tournaments/cup/live/').json()['items']
        self.assertEqual(live[0]['match_id'], self.match)
        self.assertNotEqual(live[0]['series_id'], live[0]['match_id'])

    def test_anonymous_and_wrong_methods_do_not_receive_file_metadata(self):
        self.error(self.reader(None).get(self.url, HTTP_ACCEPT='application/octet-stream'), 401, 'UNAUTHENTICATED')
        client = self.reader(self.a)
        response = client.post(self.url)
        self.error(response, 405, 'METHOD_NOT_ALLOWED')
        self.assertIn('GET', response['Allow'])
        self.error(client.get(self.replay_url('cup..bad')), 404, 'NOT_FOUND')

    def test_outside_scope_sees_same_404_as_missing_even_after_archive(self):
        outsider = self.reader(self.outsider)
        missing = self.error(outsider.get(self.replay_url('missing')), 404, 'NOT_FOUND')
        self.assertEqual(self.error(outsider.get(self.url), 404, 'NOT_FOUND'), missing)
        P.archive_tournament(self.rt.vault, 'cup', self.staff.user_id)
        self.assertEqual(self.error(outsider.get(self.url), 404, 'NOT_FOUND'), missing)

    def test_role_revocation_takes_effect_on_the_next_request(self):
        organizer = self.reader(self.org)
        participant = self.reader(self.a)
        for reader in (organizer, participant):
            self.assertEqual(self.read_download(reader.get(self.url)), self.bytes)
        OrganizerAssignment.objects.filter(user=self.org).update(active=False)
        Identity.objects.filter(user=self.a).update(roster_user_id='unlinked')
        self.error(organizer.get(self.url), 404, 'NOT_FOUND')
        self.error(participant.get(self.url), 404, 'NOT_FOUND')
        get_user_model().objects.filter(pk=self.org.pk).update(is_active=False)
        self.error(organizer.get(self.url), 401, 'UNAUTHENTICATED')

    def test_archive_purges_file_but_retains_match_history(self):
        before = self.rt.flow.store.snapshot()
        with self.rt.tournaments.store.transaction() as state:
            state['tournaments']['cup']['status'] = T.COMPLETED
        result = T.archive(self.rt.tournaments, self.staff, 'cup', self.rt.vault, confirm=True)
        self.assertTrue(result['replays_deleted'])
        self.assertFalse(self.vault_file.exists())
        self.assertEqual(self.rt.flow.store.snapshot(), before)
        for user in (self.a, self.org, self.admin):
            self.error(self.reader(user).get(self.url), 410, 'EXPIRED')
        T.delete(self.rt.tournaments, self.staff, 'cup', 'Local cleanup', confirm=True)
        self.error(self.reader(self.admin).get(self.url), 404, 'NOT_FOUND')

    def test_authoritative_archive_hides_a_lingering_file(self):
        with self.rt.tournaments.store.transaction() as state:
            state['tournaments']['cup']['status'] = T.ARCHIVED
        self.assertTrue(self.vault_file.exists())
        self.error(self.reader(self.admin).get(self.url), 410, 'EXPIRED')

    def test_archive_during_verification_never_hands_out_open_descriptor(self):
        hash_replay = P._hash_replay
        opened = []

        def archive_after_hash(stream, limit):
            result = hash_replay(stream, limit)
            opened.append(stream)
            P.archive_tournament(self.rt.vault, 'cup', self.staff.user_id)
            return result

        with patch.object(P, '_hash_replay', side_effect=archive_after_hash):
            self.error(self.reader(self.a).get(self.url), 410, 'EXPIRED')
        self.assertTrue(opened[0].closed)
        self.assertFalse(self.vault_file.exists())
        self.assertEqual(self.rt.vault.index.snapshot()['incidents'], [])

    def test_bad_file_returns_generic_503_and_records_one_incident(self):
        self.vault_file.write_bytes(gzip.compress(b'Different, structurally valid replay.'))
        client = self.reader(self.a)
        for _ in range(2):
            self.error(client.get(self.url, HTTP_ACCEPT='application/octet-stream'), 503, 'SERVICE_UNAVAILABLE')
        state = self.rt.vault.index.snapshot()
        self.assertEqual(state['replays'][self.match]['status'], P.UNAVAILABLE)
        self.assertEqual([item['incident_type'] for item in state['incidents']], ['replay_file_damaged'])

    def test_download_does_not_follow_vault_folder_links(self):
        base = self.vault_file.parent
        renamed = base.with_name('moved-replay-directory')
        base.rename(renamed)
        base.symlink_to(renamed, target_is_directory=True)
        self.error(self.reader(self.a).get(self.url), 503, 'SERVICE_UNAVAILABLE')
