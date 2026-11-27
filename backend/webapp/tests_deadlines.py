# SPDX-License-Identifier: AGPL-3.0-only
"""Admin session, deadline mutation, and notification recovery regressions."""
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from backend.notifications import notifications as N
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T
from . import domain as D
from .models import OrganizerAssignment
from . import tests as fixtures


EXTEND = '/api/v1/tournaments/cup/extend-deadline/'
OVERRIDE = '/api/v1/tournaments/cup/emergency-override/'


class DeadlineAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.FeatureAPI.setUpTestData.__func__(cls)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(BIO_DATA_DIR=Path(directory.name))
        settings.enable()
        self.addCleanup(settings.disable)
        self.rt = D.runtime()
        self.now = time.time()
        self.clock = lambda: self.now - 5000
        fixtures.FeatureAPI.make_cup(self, 'cup', self.now - 3000, self.now - 1000)
        G.import_roster(self.rt.registration, fixtures.ADM, 'cup', [
            {'email': f'{name}@uni.edu', 'team_key': f't{name}', 'team_name': f'Team {name}',
             'member_number': 1, 'role': 'captain'} for name in ('a', 'b')
        ], now=self.clock)
        codes = {row['entry_id']: row['code']
                 for row in G.issue_codes(self.rt.registration, fixtures.ADM, 'cup', now=self.clock)['issued']}
        for row in G.list_roster(self.rt.registration, fixtures.ADM, 'cup'):
            name = row['email'].split('@')[0]
            G.claim(self.rt.registration, 'cup', row['email'], codes[row['id']], f'roster-{name}', now=self.clock)
        G.confirm_email(self.rt.registration, 'cup', 'roster-a', now=self.clock)
        self.body = {
            'deadline_type': T.SUBMISSION, 'new_deadline': self.future(),
            'confirm': True, 'reason': 'Room schedule changed',
        }

    def future(self, seconds=3600):
        return datetime.fromtimestamp(self.now + seconds, timezone.utc).isoformat(timespec='seconds')

    def session(self, user):
        browser = Client(enforce_csrf_checks=True)
        if user:
            browser.force_login(user)
        token = browser.get('/api/v1/auth/session/').json()['csrf']
        return browser, token

    def post(self, login, *, path=EXTEND, body=None, key='deadline-one', csrf=True):
        browser, token = login
        headers = {'HTTP_IDEMPOTENCY_KEY': key}
        if csrf:
            headers['HTTP_X_CSRFTOKEN'] = token
        return browser.post(path, json.dumps(self.body if body is None else body),
                            content_type='application/json', **headers)

    def audit(self, action):
        return [event for event in T.audit_log(self.rt.tournaments, fixtures.ADM, 'cup')
                if event['action'] == action]

    def test_extension_notifies_registered_and_pending_accounts_even_with_email_off(self):
        browser, token = self.session(self.a)
        preference = browser.patch('/api/v1/me/notification-preferences/',
                                   json.dumps({'email_enabled': False}), content_type='application/json',
                                   HTTP_X_CSRFTOKEN=token)
        self.assertEqual(preference.status_code, 200, preference.content)
        response = self.post(self.session(self.admin))
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        self.assertEqual(result['affected_participants'], 2)
        self.assertEqual(result['notification_status'], 'published')
        self.assertEqual(T.deadline(self.rt.tournaments, 'cup', T.SUBMISSION), int(self.now + 3600))
        self.assertEqual(self.audit('extend_deadline')[0]['id'], result['audit_event_id'])
        self.assertEqual(result['audit_event_id'], result['notification_event_id'])
        items = browser.get('/api/v1/notifications/').json()['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['event_type'], 'deadline_extended')
        self.assertIn(self.body['reason'], items[0]['body'])
        state = self.rt.notifications.store.snapshot()
        self.assertEqual({item['recipient'] for item in state['notifications'].values()}, {'roster-a', 'roster-b'})
        self.assertEqual([item['recipient'] for item in state['deliveries'].values()], ['roster-b'])

    def test_only_current_admin_can_submit_or_replay_and_csrf_is_required(self):
        admin = self.session(self.admin)
        self.assertEqual(self.post(admin, csrf=False).status_code, 403)
        self.assertEqual(self.post(self.session(None)).status_code, 401)
        for user in (self.a, self.org):
            self.assertEqual(self.post(self.session(user)).status_code, 403)
        OrganizerAssignment.objects.filter(user=self.org).update(active=False)
        self.assertEqual(self.post(self.session(self.org)).status_code, 404)
        self.assertEqual(self.audit('extend_deadline'), [])
        self.assertEqual(self.post(admin).status_code, 200)
        get_user_model().objects.filter(pk=self.admin.pk).update(is_superuser=False)
        self.assertEqual(self.post(admin).status_code, 404)
        self.assertEqual(len(self.audit('extend_deadline')), 1)

    def test_invalid_schema_deadline_and_key_conflict_leave_existing_state(self):
        admin = self.session(self.admin)
        before = self.rt.tournaments.store.snapshot()
        for change in ({'confirm': 1}, {'new_deadline': '2027-01-01T12:00:00'},
                       {'deadline_type': ['submission']}, {'reason': ' '}, {'other': True},
                       {'deadline_type': T.REGISTRATION}):
            response = self.post(admin, body={**self.body, **change})
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.post(admin, key='').status_code, 400)
        self.assertEqual(self.rt.tournaments.store.snapshot(), before)
        first = self.post(admin).json()
        self.assertEqual(self.post(admin).json(), first)
        conflict = self.post(admin, body={**self.body, 'new_deadline': self.future(7200)})
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(len(self.audit('extend_deadline')), 1)
        self.assertEqual(len(self.rt.notifications.store.snapshot()['notifications']), 2)

    def test_locked_override_records_reason_without_moving_deadlines(self):
        admin = self.session(self.admin)
        body = {'setting': 'name', 'value': 'Updated Cup', 'confirm': True, 'reason': 'Correction'}
        original = self.rt.tournaments.store.snapshot()['tournaments']['cup']['deadlines']
        response = self.post(admin, path=OVERRIDE, body=body)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['tournament']['name'], 'Updated Cup')
        self.assertEqual(self.rt.tournaments.store.snapshot()['tournaments']['cup']['deadlines'], original)
        self.assertEqual(self.audit('emergency_override')[0]['reason'], 'Correction')
        notice = self.session(self.a)[0].get('/api/v1/notifications/').json()['items'][0]
        self.assertIn('name changed', notice['body'])
        self.assertIn(f'authorized by {self.admin.pk}', notice['body'])
        self.assertIn('Correction', notice['body'])
        self.assertEqual(self.post(admin, key='later-extension').status_code, 200)
        self.assertEqual(self.post(admin, path=OVERRIDE, body=body, key='unlocked').status_code, 409)

    def test_pinned_entries_block_deadline_reopening_even_if_status_is_open(self):
        R.pin_tournament(self.rt.flow.registry, 'cup', ['ta'], deadline_at=self.now - 1000)
        response = self.post(self.session(self.admin))
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(self.audit('extend_deadline'), [])

    def test_notification_store_outage_is_retried_by_maintenance(self):
        admin = self.session(self.admin)
        with patch.object(N, 'notify_notice', side_effect=OSError('fixture offline')):
            response = self.post(admin)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['notification_status'], 'pending')
        self.assertIn(result['notification_event_id'], T.pending_notices(self.rt.tournaments))
        self.assertFalse(self.rt.notifications.store.snapshot()['notifications'])
        with patch('backend.services.runner.M.load_engine_maps', return_value={}):
            self.assertEqual(D.runtime().maintenance()['deadline_notices_pending'], 0)
        self.assertFalse(T.pending_notices(self.rt.tournaments))
        self.assertEqual(self.post(admin).json()['notification_status'], 'published')
        self.assertEqual(len(self.audit('extend_deadline')), 1)
        self.assertEqual(len(self.rt.notifications.store.snapshot()['notifications']), 2)

    def test_interrupted_receipt_acknowledgement_does_not_duplicate_notices(self):
        admin = self.session(self.admin)
        with patch.object(T, 'mark_notice_published', side_effect=OSError('fixture interruption')):
            result = self.post(admin).json()
        self.assertEqual(result['notification_status'], 'pending')
        notices = self.rt.notifications.store.snapshot()
        self.assertEqual(len(notices['notifications']), 2)
        self.assertEqual(self.post(admin).json()['notification_status'], 'published')
        self.assertEqual(self.rt.notifications.store.snapshot(), notices)
        self.assertEqual(len(self.audit('extend_deadline')), 1)

    def test_full_audit_aborts_deadline_and_leaves_no_delivery_record(self):
        before = self.rt.tournaments.store.snapshot()
        with patch.object(T, 'MAX_AUDIT', 0):
            self.assertEqual(self.post(self.session(self.admin)).status_code, 409)
        self.assertEqual(self.rt.tournaments.store.snapshot(), before)
        self.assertFalse(self.rt.notifications.store.snapshot()['notifications'])
