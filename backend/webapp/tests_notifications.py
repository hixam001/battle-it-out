# SPDX-License-Identifier: AGPL-3.0-only
"""Recipient privacy and session/CSRF against PostgreSQL and the shared outbox."""
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient

from backend.notifications import notifications as N
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T
from . import domain as D
from .models import Identity


FEED = '/api/v1/notifications/'
PREFERENCES = '/api/v1/me/notification-preferences/'
PASSWORD = 'notification-test-fixture-passphrase'


class NotificationAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        for name in ('alice', 'bob', 'teammate', 'unlinked', 'organizer'):
            user = users.objects.create_user(name, email=f'{name}@example.org', password=PASSWORD)
            setattr(cls, name, user)
            if name in ('alice', 'bob', 'teammate'):
                Identity.objects.create(user=user, role='participant', roster_user_id='roster-' + name)
        Identity.objects.create(user=cls.organizer, role='organizer')
        cls.admin = users.objects.create_superuser('admin', email='admin@example.org', password=PASSWORD)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        override = override_settings(BIO_DATA_DIR=self.root)
        override.enable()
        self.addCleanup(override.disable)
        self.rt = D.runtime()
        admin = R.Actor('fixture-admin', 'admin')
        now = time.time()
        T.create(self.rt.tournaments, admin, 'cup', 'Fixture cup', '', now + 3600, now + 7200,
                 idempotency_key='fixture-cup')
        T.approve(self.rt.tournaments, admin, 'cup', confirm=True)
        T.open_registration(self.rt.tournaments, admin, 'cup')
        G.import_roster(self.rt.registration, admin, 'cup', [
            {'email': f'{name}@example.org', 'team_key': team, 'team_name': team,
             'member_number': number, 'role': role}
            for name, team, number, role in (
                ('alice', 'alpha', 1, 'captain'), ('teammate', 'alpha', 2, 'member'),
                ('bob', 'beta', 1, 'captain'))])
        codes = {row['entry_id']: row['code'] for row in G.issue_codes(self.rt.registration, admin, 'cup')['issued']}
        for row in G.list_roster(self.rt.registration, admin, 'cup'):
            uid = 'roster-' + row['email'].split('@')[0]
            G.claim(self.rt.registration, 'cup', row['email'], codes[row['id']], uid)
            G.confirm_email(self.rt.registration, 'cup', uid)
        self.first = self.notice('roster-alice', 'first', 100)
        self.second = self.notice('roster-alice', 'second', 200)
        self.historical = self.notice('roster-alice', 'historical', 300, tid='old-cup')
        self.bobs = self.notice('roster-bob', 'bob-only', 400)
        self.teammates = self.notice('roster-teammate', 'teammate-only', 500)
        self.client = APIClient()
        self.client.force_authenticate(self.alice)

    def notice(self, recipient, key, at, tid='cup'):
        N.notify(self.rt.notifications, 'announcement', tid, [recipient],
                 {'headline': key, 'message': 'Fixture notice.'}, event_key=key, now=lambda: at)
        rows = N.list_notifications(self.rt.notifications, R.Actor(recipient, 'participant'))['items']
        return next(row['id'] for row in rows if row['title'] == key)

    def patch(self, path, body):
        return self.client.patch(path, body, format='json')

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        error = response.json()['error']
        self.assertEqual(error['code'], code)
        self.assertEqual(error['request_id'], response['X-Request-ID'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        return {key: value for key, value in error.items() if key != 'request_id'}

    def test_anonymous_feed_and_mutations_require_login(self):
        self.client.force_authenticate(None)
        before = self.rt.notifications.store.snapshot()
        for response in (self.client.get(FEED), self.client.get(PREFERENCES),
                         self.patch(FEED + self.first + '/', {'read': True}),
                         self.patch(PREFERENCES, {'email_enabled': False})):
            self.assert_error(response, 401, 'UNAUTHENTICATED')
        self.assertEqual(before, self.rt.notifications.store.snapshot())

    def test_feed_projects_only_own_notifications_and_safe_fields(self):
        with self.rt.notifications.store.transaction() as state:
            state['deliveries'][self.first]['last_error'] = 'PRIVATE-PROVIDER-FIXTURE'
        response = self.client.get(FEED)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertRegex(response['X-Request-ID'], r'^req_[0-9a-f]{32}$')
        data = response.json()
        self.assertEqual((data['total'], data['unread']), (3, 3))
        self.assertEqual([row['id'] for row in data['items']], [self.historical, self.second, self.first])
        for row in data['items']:
            self.assertEqual(set(row), {'id', 'tournament_id', 'event_type', 'title', 'body',
                                       'created_at', 'read', 'read_at', 'email_status'})
        text = response.content.decode()
        for private in ('recipient', 'event_key', 'roster-alice', 'PRIVATE-PROVIDER-FIXTURE', str(self.root)):
            self.assertNotIn(private, text)

    def test_same_team_foreign_and_missing_notifications_share_404(self):
        before = self.rt.notifications.store.snapshot()
        errors = [self.assert_error(self.patch(FEED + nid + '/', {'read': True}), 404, 'NOT_FOUND')
                  for nid in (self.bobs, self.teammates, 'n-missing')]
        self.assertEqual(errors, [errors[0]] * 3)
        self.assertEqual(before, self.rt.notifications.store.snapshot())

    def test_feed_filters_counts_and_bounded_pagination(self):
        self.patch(FEED + self.first + '/', {'read': True})
        data = self.client.get(FEED + '?tournament_id=cup&limit=1&offset=1').json()
        self.assertEqual([row['id'] for row in data['items']], [self.first])
        self.assertEqual((data['total'], data['unread']), (2, 1))
        unread = self.client.get(FEED + '?tournament_id=cup&unread_only=true').json()
        self.assertEqual([row['id'] for row in unread['items']], [self.second])
        self.assertEqual((unread['total'], unread['unread']), (1, 1))
        self.assertEqual(self.client.get(FEED + '?offset=2147483647').json()['items'], [])
        self.assertEqual(self.client.get(FEED + '?limit=200').status_code, 200)
        self.assertEqual(self.client.get(FEED + '?tournament_id=missing').json(), {'items': [], 'total': 0, 'unread': 0})

    def test_paging_order_is_stable_when_timestamps_tie(self):
        third = self.notice('roster-alice', 'same-time', 200)
        whole = self.client.get(FEED).json()['items']
        paged = [self.client.get(FEED + f'?limit=1&offset={offset}').json()['items'][0] for offset in range(4)]
        self.assertEqual(whole, paged)
        self.assertEqual([row['id'] for row in whole[1:3]], sorted([third, self.second]))

    def test_query_rejects_invalid_unknown_and_duplicate_values(self):
        before = self.rt.notifications.store.snapshot()
        for query in ('limit=0', 'limit=201', 'limit=-1', 'limit=1.5', 'limit=true', 'limit=',
                      'offset=-1', 'offset=2147483648', 'offset=1.0', 'offset=' + '9' * 5000,
                      'unread_only=1', 'unread_only=TRUE', 'tournament_id=../cup', 'tournament_id=',
                      'recipient=roster-bob', 'user_id=roster-bob', 'limit=1&limit=2',
                      'tournament_id=cup&tournament_id=old-cup'):
            with self.subTest(query=query[:100]):
                self.assert_error(self.client.get(FEED + '?' + query), 400, 'VALIDATION_ERROR')
        self.assertEqual(before, self.rt.notifications.store.snapshot())

    def test_read_setter_is_idempotent_and_can_mark_unread(self):
        path = FEED + self.first + '/'
        first = self.patch(path, {'read': True})
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()['read'])
        self.assertIsNotNone(first.json()['read_at'])
        before = self.rt.notifications.store.snapshot()
        repeated = self.patch(path, {'read': True})
        self.assertEqual(first.json(), repeated.json())
        self.assertNotEqual(first['X-Request-ID'], repeated['X-Request-ID'])
        self.assertEqual(before, self.rt.notifications.store.snapshot())
        unread = self.patch(path, {'read': False}).json()
        self.assertFalse(unread['read'])
        self.assertIsNone(unread['read_at'])

    def test_invalid_read_bodies_and_media_do_not_mutate(self):
        before = self.rt.notifications.store.snapshot()
        path = FEED + self.first + '/'
        for body in ({}, {'read': 'true'}, {'read': 1}, {'read': None}, {'read': True, 'recipient': 'roster-bob'}, [], None):
            with self.subTest(body=body):
                response = self.client.generic('PATCH', path, json.dumps(body), content_type='application/json')
                self.assert_error(response, 400, 'VALIDATION_ERROR')
        self.assert_error(self.client.generic('PATCH', path, '{', content_type='application/json'), 400, 'VALIDATION_ERROR')
        self.assert_error(self.client.generic('PATCH', path, 'read=true', content_type='application/x-www-form-urlencoded'),
                          415, 'UNSUPPORTED_MEDIA_TYPE')
        self.assertEqual(before, self.rt.notifications.store.snapshot())

    def test_preference_default_setter_and_restart_use_the_shared_store(self):
        self.assertEqual(self.client.get(PREFERENCES).json(), {'email_enabled': True, 'dashboard_enabled': True})
        disabled = self.patch(PREFERENCES, {'email_enabled': False})
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(disabled.json(), {'email_enabled': False, 'dashboard_enabled': True})
        before = self.rt.notifications.store.snapshot()
        self.assertEqual(self.patch(PREFERENCES, {'email_enabled': False}).json(), disabled.json())
        self.assertEqual(before, self.rt.notifications.store.snapshot())
        # A fresh service runtime reads the HTTP preference, not another SQL/default preference.
        fresh = D.runtime()
        self.assertFalse(N.get_preferences(fresh.notifications, R.Actor('roster-alice', 'participant'))['email_enabled'])
        self.assertEqual(self.client.get(PREFERENCES).json(), disabled.json())
        self.client.force_authenticate(self.bob)
        self.assertTrue(self.client.get(PREFERENCES).json()['email_enabled'])
        self.client.force_authenticate(self.alice)
        self.assertTrue(self.patch(PREFERENCES, {'email_enabled': True}).json()['email_enabled'])
        new_id = self.notice('roster-alice', 'email-reenabled', 600)
        self.assertEqual(D.runtime().notifications.store.snapshot()['notifications'][new_id]['email_status'], 'pending')

    def test_preference_conflict_rolls_back_and_uses_shared_error_envelope(self):
        before = self.rt.notifications.store.snapshot()
        with patch.object(N, 'MAX_AUDIT', 0):
            self.assert_error(self.patch(PREFERENCES, {'email_enabled': False}), 409, 'STATE_CONFLICT')
        self.assertEqual(before, self.rt.notifications.store.snapshot())

    def test_preferences_reject_dashboard_disable_and_identity_injection(self):
        before = self.rt.notifications.store.snapshot()
        for body in ({}, {'dashboard_enabled': False}, {'email_enabled': False, 'dashboard_enabled': False},
                     {'email_enabled': 0}, {'email_enabled': 'false'}, {'email_enabled': None},
                     {'email_enabled': False, 'user_id': 'roster-bob'}, []):
            with self.subTest(body=body):
                self.assert_error(self.patch(PREFERENCES, body), 400, 'VALIDATION_ERROR')
        self.assert_error(self.client.generic('PATCH', PREFERENCES, 'email_enabled=false', content_type='text/plain'),
                          415, 'UNSUPPORTED_MEDIA_TYPE')
        self.assertEqual(before, self.rt.notifications.store.snapshot())

    def test_email_disabled_keeps_new_team_notices_and_skips_existing_outbox(self):
        self.patch(PREFERENCES, {'email_enabled': False})
        created = N.notify_audience(D.runtime().notifications, self.rt.registration, 'qualified', 'cup',
                                    {'team': 'alpha', 'round': 1}, event_key='fixture-qualified', team_id='alpha')
        self.assertEqual((created['created'], created['email_queued']), (2, 1))
        # No provider is contacted: these injected failures exercise outbox isolation.
        def unavailable(message):
            raise RuntimeError('Fixture provider outage')
        report = N.deliver_emails(D.runtime().notifications, unavailable, lambda uid: 'fixture@example.org')
        self.assertEqual(report['skipped'], 3)
        self.assertGreater(report['retry'], 0)
        feed = self.client.get(FEED).json()
        self.assertEqual(feed['total'], 4)
        self.assertEqual(feed['items'][0]['event_type'], 'qualified')
        self.assertEqual(feed['items'][0]['email_status'], 'disabled')
        self.assertEqual(N.notify_audience(self.rt.notifications, self.rt.registration, 'qualified', 'cup',
                                         {'team': 'alpha', 'round': 1}, event_key='fixture-qualified', team_id='alpha')['created'], 0)
        self.assertEqual(self.client.get(FEED).json()['total'], 4)

    def test_explicit_link_prevents_numeric_account_and_roster_id_collision(self):
        collision = self.notice(str(self.unlinked.pk), 'foreign-numeric-recipient', 600)
        for user in (self.unlinked, self.organizer, self.admin):
            self.client.force_authenticate(user)
            self.assert_error(self.client.get(FEED), 403, 'FORBIDDEN')
            self.assert_error(self.client.get(PREFERENCES), 403, 'FORBIDDEN')
            self.assert_error(self.patch(FEED + collision + '/', {'read': True}), 403, 'FORBIDDEN')
            self.assert_error(self.patch(PREFERENCES, {'email_enabled': False}), 403, 'FORBIDDEN')
        self.assertIsNone(self.rt.notifications.store.snapshot()['notifications'][collision]['read_at'])

    def test_link_is_reread_before_next_read_and_write(self):
        self.assertEqual(self.client.get(FEED).status_code, 200)
        Identity.objects.filter(user=self.alice).update(roster_user_id=None)
        before = self.rt.notifications.store.snapshot()
        self.assert_error(self.client.get(FEED), 403, 'FORBIDDEN')
        self.assert_error(self.patch(FEED + self.first + '/', {'read': True}), 403, 'FORBIDDEN')
        self.assert_error(self.patch(PREFERENCES, {'email_enabled': False}), 403, 'FORBIDDEN')
        self.assertEqual(before, self.rt.notifications.store.snapshot())

    def test_personal_historical_notices_do_not_require_current_tournament_access(self):
        with self.rt.tournaments.store.transaction() as state:
            state['tournaments']['cup']['status'] = 'archived'
        self.assertNotIn('old-cup', D.actor(self.alice).tournament_ids)
        historical = self.client.get(FEED + '?tournament_id=old-cup').json()
        self.assertEqual([row['id'] for row in historical['items']], [self.historical])
        self.assertEqual(self.patch(FEED + self.historical + '/', {'read': True}).status_code, 200)

    def test_real_sessions_enforce_csrf_and_deactivation(self):
        client = Client(enforce_csrf_checks=True)
        csrf = client.get('/api/v1/auth/session/').json()['csrf']
        login = client.post('/api/v1/auth/login/', json.dumps({'username': 'alice', 'password': PASSWORD}),
                            content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(client.get(FEED).json()['total'], 3)
        before = self.rt.notifications.store.snapshot()
        for path, body in ((FEED + self.first + '/', {'read': True}), (PREFERENCES, {'email_enabled': False})):
            self.assert_error(client.patch(path, json.dumps(body), content_type='application/json'), 403, 'FORBIDDEN')
        self.assertEqual(before, self.rt.notifications.store.snapshot())
        csrf = login.json()['csrf']
        self.assertEqual(client.patch(PREFERENCES, json.dumps({'email_enabled': False}),
                                      content_type='application/json', HTTP_X_CSRFTOKEN=csrf).status_code, 200)
        self.assertEqual(client.patch(FEED + self.first + '/', json.dumps({'read': True}),
                                      content_type='application/json', HTTP_X_CSRFTOKEN=csrf).status_code, 200)
        get_user_model().objects.filter(pk=self.alice.pk).update(is_active=False)
        self.assert_error(client.get(FEED), 401, 'UNAUTHENTICATED')
        self.assert_error(client.patch(FEED + self.first + '/', json.dumps({'read': True}),
                                       content_type='application/json', HTTP_X_CSRFTOKEN=csrf), 401, 'UNAUTHENTICATED')

    def test_unsupported_methods_preserve_allow_header_and_state(self):
        before = self.rt.notifications.store.snapshot()
        response = self.client.post(FEED, {}, format='json')
        self.assert_error(response, 405, 'METHOD_NOT_ALLOWED')
        self.assertIn('GET', response['Allow'])
        self.assert_error(self.client.delete(FEED + self.first + '/'), 405, 'METHOD_NOT_ALLOWED')
        self.assertEqual(before, self.rt.notifications.store.snapshot())
