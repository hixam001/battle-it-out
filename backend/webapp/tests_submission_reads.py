# SPDX-License-Identifier: AGPL-3.0-only
"""Submission history, validation, and staff audit at the HTTP boundary."""
from django.test import Client, TestCase

from backend.registration import registration as G
from backend.submission_registry import registry as R
from .models import AuditEvent, OrganizerAssignment
from .tests import BOT, FeatureAPI


class SubmissionReadsAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        FeatureAPI.setUpTestData.__func__(cls)

    def setUp(self):
        self.fixture = FeatureAPI()
        self.fixture.a = self.a
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.runtime = self.fixture.rt

    def reader(self, user):
        client = Client()
        client.force_login(user)
        return client

    def history(self, team='ta', tid='cup'):
        return f'/api/v1/tournaments/{tid}/teams/{team}/submissions/'

    def validation(self, sid='ta-v1', tid='cup'):
        return f'/api/v1/tournaments/{tid}/submissions/{sid}/validation/'

    def hidden(self, response):
        self.assertEqual(response.status_code, 404)
        error = response.json()['error']
        self.assertEqual(error.pop('request_id'), response['X-Request-ID'])
        return error

    def test_history_links_an_exact_version_to_official_game_ids(self):
        response = self.reader(self.a).get(self.history())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        (version,) = response.json()['items']
        games = self.runtime.flow.store.snapshot()['series'][self.fixture.sid]['games']
        self.assertEqual(version['match_ids'], [games[0]['match_id']])
        self.assertEqual(version['id'], 'ta-v1')
        self.assertTrue(version['is_active'])
        self.assertFalse(AuditEvent.objects.filter(action='submission_history_read').exists())

    def test_validation_exposes_current_state_and_ordered_checks(self):
        response = self.reader(self.a).get(self.validation())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        result = response.json()
        self.assertEqual(set(result), {'id', 'team_id', 'tournament_id', 'version', 'is_active',
                                       'validation_status', 'check_in_progress', 'validations'})
        self.assertEqual(result['validation_status'], R.VALID)
        self.assertEqual([entry['status'] for entry in result['validations']], ['passed', 'valid'])
        self.assertTrue(result['is_active'])
        self.assertFalse(result['check_in_progress'])
        self.assertFalse(AuditEvent.objects.filter(action='submission_validation_read').exists())

    def test_static_refusal_and_claimed_trial_are_readable_without_claim_data(self):
        tid, team = 'future', 'future-a'
        self.fixture.make_cup(tid, self.fixture.now+1000, self.fixture.now+2000)
        self.fixture.register(tid, [('a', team)])
        actor = G.actor_for(self.runtime.registration, 'roster-a')
        registry = self.runtime.flow.registry
        good = R.submit(registry, actor, team, tid, 'bot.py', BOT, idempotency_key='pending',
                        deadline_at=self.fixture.now+2000)
        claim = R.claim_check(registry, good['id'])
        bad = R.submit(registry, actor, team, tid, 'bot.py', b'def invalid(', idempotency_key='invalid',
                       deadline_at=self.fixture.now+2000)
        client = self.reader(self.a)
        pending = client.get(self.validation(good['id'], tid))
        self.assertEqual(pending.json()['validation_status'], R.VALIDATING)
        self.assertTrue(pending.json()['check_in_progress'])
        self.assertNotIn(claim.token.encode(), pending.content)
        refused = client.get(self.validation(bad['id'], tid)).json()
        self.assertEqual(refused['validation_status'], R.INVALID)
        self.assertTrue(refused['validations'][0]['reasons'][0]['message'])
        self.assertFalse(refused['is_active'])
        self.assertEqual([item['match_ids'] for item in client.get(self.history(team, tid)).json()['items']], [[], []])

    def test_current_staff_reads_are_audited_and_revocation_removes_access(self):
        for user in (self.org, self.admin):
            with self.subTest(user=user.username):
                client = self.reader(user)
                self.assertEqual(client.get(self.history('tb')).status_code, 200)
                self.assertEqual(client.get(self.validation('tb-v1')).status_code, 200)
                events = AuditEvent.objects.filter(actor_id_text=str(user.pk), tournament_id='cup')
                self.assertEqual(events.get(action='submission_history_read').detail, {'team_id': 'tb'})
                self.assertEqual(events.get(action='submission_validation_read').detail, {'submission_id': 'tb-v1'})
        organizer = self.reader(self.org)
        OrganizerAssignment.objects.filter(user=self.org).update(active=False)
        self.hidden(organizer.get(self.history('tb')))
        self.hidden(organizer.get(self.validation('tb-v1')))
        self.assertEqual(AuditEvent.objects.filter(actor_id_text=str(self.org.pk), tournament_id='cup').count(), 2)

    def test_unknown_ids_and_another_team_have_the_same_refusal(self):
        self.assertEqual(Client().get(self.validation()).status_code, 401)
        client = self.reader(self.a)
        self.assertEqual(self.hidden(client.get(self.validation('tb-v1'))),
                         self.hidden(client.get(self.validation('missing'))))
        self.assertEqual(self.hidden(client.get(self.history('tb'))), self.hidden(client.get(self.history('missing'))))

    def test_scope_matches_the_requested_tournament_and_empty_roster_history_is_readable(self):
        self.fixture.make_cup('other', self.fixture.now+1000, self.fixture.now+2000)
        self.fixture.register('other', [('a', 'empty-team')])
        admin = self.reader(self.admin)
        self.hidden(admin.get(self.validation(tid='other')))
        self.hidden(admin.get(self.history(tid='other')))
        self.hidden(admin.get(self.history('missing', 'other')))
        self.assertEqual(admin.get(self.history('empty-team', 'other')).json(), {'items': []})
        self.assertEqual(self.reader(self.a).get(self.history('empty-team', 'other')).json(), {'items': []})
