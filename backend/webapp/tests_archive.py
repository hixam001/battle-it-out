# SPDX-License-Identifier: AGPL-3.0-only
"""Confirmed, scoped archive against disposable tournament and replay state."""
import gzip
import json
from unittest.mock import patch

from django.test import Client, TestCase

from backend.match_orchestrator import replays as P
from backend.tournaments import tournaments as T
from .models import OrganizerAssignment
from .tests import FeatureAPI


class ArchiveAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        FeatureAPI.setUpTestData.__func__(cls)

    def setUp(self):
        fixture = FeatureAPI()
        fixture.a = self.a
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.rt = fixture.rt
        self.tournaments = self.rt.tournaments.store
        self.mid = self.rt.flow.store.snapshot()['series'][fixture.sid]['games'][0]['match_id']
        self.url = '/api/v1/tournaments/cup/archive/'
        self.source = fixture.root / 'fixture.bc26'
        self.source.write_bytes(gzip.compress(b'Temporary archive replay fixture.'))
        P.register_replay(self.rt.vault, 'cup', self.mid, self.source, None)
        P.register_replay(self.rt.vault, 'other-cup', 'other-game', self.source, None)
        self.stored = self.rt.vault.root / 'cup' / f'{self.mid}.bc26'
        self.set_status(T.COMPLETED)

    def set_status(self, status):
        with self.tournaments.transaction() as state:
            state['tournaments']['cup']['status'] = status

    def browser(self, user):
        client = Client(enforce_csrf_checks=True)
        if user is not None:
            client.force_login(user)
        token = client.get('/api/v1/auth/session/').json()['csrf']
        return client, token

    def post(self, browser, body=None, *, csrf=True, url=None, content_type='application/json'):
        client, token = browser
        data = json.dumps({'confirm': True} if body is None else body)
        headers = {'HTTP_X_CSRFTOKEN': token} if csrf else {}
        return client.post(url or self.url, data, content_type=content_type, **headers)

    def error(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        payload = response.json()['error']
        self.assertEqual(payload.pop('request_id'), response['X-Request-ID'])
        self.assertEqual(payload['code'], code)
        return payload

    def test_assigned_organizer_archives_with_verified_purge_and_retained_history(self):
        history = self.rt.flow.store.snapshot()
        browser = self.browser(self.org)
        response = self.post(browser)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'archived', 'replays_deleted': True})
        self.assertFalse(self.stored.exists())
        self.assertTrue((self.rt.vault.root / 'other-cup' / 'other-game.bc26').exists())
        self.assertEqual(self.rt.flow.store.snapshot(), history)
        with self.assertRaises(P.Gone):
            P.fetch_replay(self.rt.vault, self.mid, P.Viewer('admin'))
        self.assertEqual(browser[0].get('/api/v1/tournaments/cup/live/').status_code, 410)
        self.assertEqual(browser[0].get('/api/v1/tournaments/cup/analytics/').json()['totals']['completed'], 1)

        state = self.tournaments.snapshot()
        self.assertEqual(self.post(browser).json(), response.json())
        self.assertEqual(self.tournaments.snapshot(), state)
        archive = [item for item in state['audit'] if item['action'] == 'archive']
        self.assertEqual(len(archive), 1)
        self.assertEqual(archive[0]['actor'], str(self.org.pk))

    def test_access_requires_current_explicit_assignment_or_admin(self):
        # Match the author but revoke the assignment: the legacy creator fallback cannot grant HTTP access.
        with self.tournaments.transaction() as state:
            state['tournaments']['cup']['created_by'] = str(self.org.pk)
        before = self.tournaments.snapshot()
        organizer = self.browser(self.org)
        OrganizerAssignment.objects.filter(user=self.org).update(active=False)
        hidden = self.error(self.post(organizer), 404, 'NOT_FOUND')
        self.assertEqual(hidden, self.error(self.post(organizer, url='/api/v1/tournaments/missing/archive/'),
                                           404, 'NOT_FOUND'))
        self.error(self.post(self.browser(self.a)), 403, 'FORBIDDEN')
        self.error(self.post(self.browser(None)), 401, 'UNAUTHENTICATED')
        self.assertEqual(self.tournaments.snapshot(), before)
        self.assertTrue(self.stored.exists())
        self.assertEqual(self.post(self.browser(self.admin)).status_code, 200)

    def test_csrf_json_and_exact_confirmation_are_required(self):
        admin = self.browser(self.admin)
        before = self.tournaments.snapshot()
        self.error(self.post(admin, csrf=False), 403, 'FORBIDDEN')
        self.error(self.post(admin, content_type='text/plain'), 415, 'UNSUPPORTED_MEDIA_TYPE')
        for body in ({}, {'confirm': False}, {'confirm': 1}, {'confirm': 'true'},
                     {'confirm': True, 'actor': 'admin'}, [True]):
            self.error(self.post(admin, body), 400, 'VALIDATION_ERROR')
        self.assertEqual(self.tournaments.snapshot(), before)
        self.assertTrue(self.stored.exists())

    def test_running_conflicts_and_deleted_is_hidden(self):
        admin = self.browser(self.admin)
        self.set_status(T.RUNNING)
        self.error(self.post(admin), 409, 'STATE_CONFLICT')
        self.set_status(T.DELETED)
        self.error(self.post(admin), 404, 'NOT_FOUND')
        self.assertTrue(self.stored.exists())

    def test_failed_purge_keeps_archive_access_closed_until_maintenance_retries(self):
        admin = self.browser(self.admin)
        with patch.object(P, '_purge_files', return_value=(0, 0, 'fixture filesystem failure')):
            result = self.post(admin)
        self.assertEqual(result.json(), {'status': 'archived', 'replays_deleted': False})
        self.assertTrue(self.stored.exists())
        with self.assertRaises(P.Gone):
            P.fetch_replay(self.rt.vault, self.mid, P.Viewer('admin'))
        self.assertEqual(P.purge_pending(self.rt.vault), ['cup'])
        self.assertFalse(self.stored.exists())
        self.assertTrue(self.post(admin).json()['replays_deleted'])

    def test_full_audit_refuses_before_vault_mutation(self):
        before = self.rt.vault.index.snapshot()
        with patch.object(T, 'MAX_AUDIT', 0):
            response = self.post(self.browser(self.admin))
        self.error(response, 409, 'STATE_CONFLICT')
        self.assertEqual(self.rt.vault.index.snapshot(), before)
        self.assertTrue(self.stored.exists())
