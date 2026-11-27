# SPDX-License-Identifier: AGPL-3.0-only
"""Current role and tournament scope for redacted audit feeds."""
from datetime import datetime

from django.test import Client, TestCase
from rest_framework.test import APIClient

from backend.match_orchestrator import bracket as B, orchestrator as O, tiebreak as TB
from backend.match_orchestrator.tests.test_bracket import MAPS, teams
from backend.match_orchestrator.tests.test_tiebreak import COIN, PLATFORM, won
from backend.notifications import notifications as N
from backend.registration import registration as G
from backend.tournaments import tournaments as T
from . import tests as fixtures
from .models import AuditEvent, Dispute, Identity, OrganizerAssignment


SCOPED = '/api/v1/tournaments/cup/audit-logs/'
GLOBAL = '/api/v1/admin/audit-logs/'


class AuditAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.FeatureAPI.setUpTestData.__func__(cls)

    def setUp(self):
        fixture = fixtures.FeatureAPI()
        fixture.a = self.a
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.rt = fixture.rt
        fixture.make_cup('other-cup', fixture.now + 3000, fixture.now + 5000)
        self.clock = fixture.clock
        self.own = Dispute.objects.create(tournament_id='cup', series_id=fixture.sid, team_id='ta',
                                           opened_by=self.a, title='Own case', description='Private details')
        self.foreign = Dispute.objects.create(tournament_id='cup', series_id=fixture.sid, team_id='tb',
                                               opened_by=self.b, title='Foreign case', description='Other details')
        for dispute in (self.own, self.foreign):
            AuditEvent.objects.create(
                actor_id_text=str(dispute.opened_by_id), tournament_id='cup', action='dispute_opened',
                detail={'id': str(dispute.pk), 'password': 'fixture-private', 'file': '/tmp/fixture-private.py'},
            )
        AuditEvent.objects.create(actor_id_text='operator', tournament_id='', action='roster_identity_linked',
                                  detail={'user_id': str(self.a.pk), 'reason': 'fixture-private'})
        AuditEvent.objects.create(actor_id_text='operator', tournament_id='cup', action='organizer_assigned',
                                  detail={'user_id': str(self.org.pk), 'reason': 'fixture-private'})
        N.notify(self.rt.notifications, 'announcement', 'cup', ['roster-a'],
                 {'headline': 'Notice', 'message': 'fixture-private'}, event_key='fixture-audit-notice')
        self.api = APIClient()

    @staticmethod
    def details(items, key):
        return {item['detail'][key] for item in items if key in item['detail']}

    def get(self, user, path=SCOPED, **query):
        self.api.force_authenticate(user)
        return self.api.get(path, query)

    def test_participant_sees_own_versions_and_disputes_and_public_events(self):
        result = self.get(self.a)
        self.assertEqual(result.status_code, 200, result.content)
        items = result.json()['items']
        self.assertEqual(self.details(items, 'submission_id'), {'ta-v1'})
        self.assertEqual(self.details(items, 'dispute_id'), {str(self.own.pk)})
        self.assertEqual({item['source'] for item in items}, {'web', 'submissions', 'tournament', 'series'})
        self.assertEqual({item['action'] for item in items if item['source'] == 'tournament'},
                         {'open_registration'})
        self.assertTrue(all('actor_id' not in item for item in items))
        self.assertNotIn('fixture-private', result.content.decode())
        self.assertEqual(result['Cache-Control'], 'private, no-store')

    def test_organizer_only_sees_current_assigned_audit(self):
        browser = Client()
        browser.force_login(self.org)
        response = browser.get(SCOPED)
        self.assertEqual(response.status_code, 200, response.content)
        items = response.json()['items']
        self.assertEqual({item['source'] for item in items},
                         {'tournament', 'registration', 'submissions', 'notifications', 'web', 'series'})
        self.assertEqual(self.details(items, 'dispute_id'), {str(self.own.pk), str(self.foreign.pk)})
        self.assertEqual(self.details(items, 'submission_id'), {'ta-v1', 'tb-v1'})
        self.assertNotIn('organizer_assigned', {item['action'] for item in items})
        self.assertNotIn('fixture-private', response.content.decode())
        self.assertEqual(browser.get(SCOPED.replace('/cup/', '/other-cup/')).status_code, 404)
        OrganizerAssignment.objects.filter(user=self.org).update(active=False)
        self.assertEqual(browser.get(SCOPED).status_code, 404)

    def test_admin_global_retains_audit_after_tournament_deletion(self):
        T.delete(self.rt.tournaments, fixtures.ADM, 'other-cup', 'fixture-private', confirm=True)
        result = self.get(self.admin, GLOBAL, tournament_id='other-cup')
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual({item['tournament_id'] for item in result.json()['items']}, {'other-cup'})
        deletion = result.json()['items'][0]
        self.assertEqual(deletion['action'], 'delete')
        self.assertEqual(deletion['detail']['to'], T.DELETED)
        self.assertNotIn('fixture-private', result.content.decode())
        self.assertEqual(self.get(self.admin, SCOPED.replace('/cup/', '/other-cup/')).status_code, 404)
        whole = self.get(self.admin, GLOBAL).json()['items']
        self.assertEqual({item['tournament_id'] for item in whole}, {'cup', 'other-cup', None})
        self.assertIn('roster_identity_linked', {item['action'] for item in whole})

    def test_global_feed_is_admin_only(self):
        for account, status in ((None, 401), (self.a, 403), (self.org, 403), (self.outsider, 403)):
            self.assertEqual(self.get(account, GLOBAL).status_code, status)
        self.assertEqual(self.get(None).status_code, 401)
        for path in (SCOPED, SCOPED.replace('/cup/', '/missing/')):
            hidden = self.get(self.outsider, path)
            self.assertEqual((hidden.status_code, hidden.json()['error']['code']), (404, 'NOT_FOUND'))

    def test_bounded_offset_orders_timestamp_ties_consistently_and_rejects_bad_queries(self):
        full = self.get(self.admin, GLOBAL, limit=200).json()['items']
        first = self.get(self.admin, GLOBAL, limit=3).json()
        second = self.get(self.admin, GLOBAL, limit=3, offset=first['next_offset']).json()
        self.assertEqual(first['items'] + second['items'], full[:6])
        times = [datetime.fromisoformat(item['created_at']) for item in full]
        self.assertEqual(times, sorted(times, reverse=True))
        self.assertEqual(len({item['id'] for item in full}), len(full))
        self.assertEqual(self.get(self.admin, GLOBAL, offset=len(full)).json(),
                         {'items': [], 'next_offset': None})
        for suffix in ('?limit=201', '?limit=1&limit=2', '?offset=-1', '?tournament_id=', '?other=1'):
            self.assertEqual(self.get(self.admin, GLOBAL + suffix).status_code, 400)
        self.assertEqual(self.get(self.admin, SCOPED, tournament_id='other-cup').status_code, 400)

    def test_reads_leave_stores_and_audit_append_only(self):
        before = (self.rt.tournaments.store.snapshot(), self.rt.flow.registry.store.snapshot(),
                  self.rt.flow.store.snapshot(), AuditEvent.objects.count())
        self.assertEqual(self.get(self.admin, GLOBAL).status_code, 200)
        response = self.api.post(GLOBAL, {'action': 'delete'}, format='json')
        self.assertEqual(response.status_code, 405)
        self.assertEqual((self.rt.tournaments.store.snapshot(), self.rt.flow.registry.store.snapshot(),
                          self.rt.flow.store.snapshot(), AuditEvent.objects.count()), before)

    def test_registered_team_without_a_pairing_sees_no_other_series_history(self):
        registration = self.rt.registration
        rows = [{'email': 'new-team@uni.edu', 'team_key': 'new-team', 'team_name': 'New Team',
                 'member_number': 1, 'role': 'captain'}]
        G.import_roster(registration, fixtures.ADM, 'cup', rows, now=self.clock)
        code, = G.issue_codes(registration, fixtures.ADM, 'cup', now=self.clock)['issued']
        G.claim(registration, 'cup', 'new-team@uni.edu', code['code'], 'roster-other', now=self.clock)
        G.confirm_email(registration, 'cup', 'roster-other', now=self.clock)
        Identity.objects.create(user=self.outsider, role='participant', roster_user_id='roster-other')
        result = self.get(self.outsider)
        self.assertEqual(result.status_code, 200, result.content)
        items = result.json()['items']
        self.assertIn('open_registration', {item['action'] for item in items})
        self.assertNotIn('series', {item['source'] for item in items})

    def test_official_series_coin_flip_and_incident_lifecycle_in_audit(self):
        store = self.rt.flow.store
        B.create_bracket(store, 'second-bracket', teams(2), MAPS, max_attempts=1)
        with store.transaction() as state:
            state['brackets']['second-bracket']['tournament_id'] = 'other-cup'
        B.start_round(store, 'second-bracket', 1, 'operator')
        paused = B.run_round(store, 'second-bracket', 1, lambda ctx: PLATFORM, sleep=lambda seconds: None)
        self.assertEqual(paused['status'], B.PAUSED)
        sid = B.series_id('second-bracket', 1, 0)
        match_id = TB.game_id(sid, 0)
        global_items = self.get(self.admin, GLOBAL, tournament_id='other-cup').json()['items']
        opened, = [item for item in global_items if item['source'] == 'incident']
        self.assertEqual(opened['action'], 'incident_opened')
        self.assertEqual(opened['detail']['match_id'], match_id)
        self.assertEqual(opened['detail']['attempt_count'], 1)
        self.assertNotIn('incident', {item['source'] for item in self.get(self.admin).json()['items']})

        O.resume_paused(store, match_id, 'operator')
        complete = B.run_round(store, 'second-bracket', 1, lambda ctx: won('B', COIN), coin=lambda: 'A')
        self.assertEqual(complete['status'], B.COMPLETED)
        flip = TB.get_series(store, sid)['coin_flip']
        result = self.get(self.admin, GLOBAL, tournament_id='other-cup')
        items = result.json()['items']
        incidents = [item for item in items if item['source'] == 'incident']
        self.assertEqual(incidents[1], opened)
        self.assertEqual(incidents[0]['action'], 'incident_resolved')
        self.assertEqual(incidents[0]['actor_id'], 'operator')
        event, = [item for item in items if item['action'] == 'coin_flip']
        self.assertEqual(event['detail']['coin_flip_id'], flip['id'])
        self.assertEqual(event['detail']['winner_team'], flip['result_team'])
        self.assertNotIn('/x/', result.content.decode())
        self.assertNotIn('last failure', result.content.decode())

        OrganizerAssignment.objects.create(user=self.org, tournament_id='other-cup')
        scoped = SCOPED.replace('/cup/', '/other-cup/')
        organizer_items = self.get(self.org, scoped).json()['items']
        self.assertIn('coin_flip', {item['action'] for item in organizer_items})
        self.assertNotIn('incident', {item['source'] for item in organizer_items})
        T.delete(self.rt.tournaments, fixtures.ADM, 'other-cup', 'Delete fixture', confirm=True)
        retained = self.get(self.admin, GLOBAL, tournament_id='other-cup').json()['items']
        self.assertIn(event, retained)
