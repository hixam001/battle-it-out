# SPDX-License-Identifier: AGPL-3.0-only
"""Session-scoped map selection, bracket generation and round start."""
import json

from django.test import Client, TestCase, override_settings

from backend.match_orchestrator import bracket as B, maps as M
from backend.match_orchestrator.tests.test_maps import ENGINE, FILES, GOOD, make_jar
from backend.match_orchestrator.tests.test_tiebreak import PLATFORM
from backend.notifications import notifications as N
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T
from backend.work_queue import jobs as J
from .models import OrganizerAssignment
from .tests import BOT, FeatureAPI, verdict


class RoundActionsAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        FeatureAPI.setUpTestData.__func__(cls)

    def setUp(self):
        fixture = FeatureAPI()
        fixture.a = self.a
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.rt = fixture.rt
        self.tid = 'staff-draw'
        self.prefix = f'/api/v1/tournaments/{self.tid}/'
        OrganizerAssignment.objects.create(user=self.org, tournament_id=self.tid)
        fixture.make_cup(self.tid, fixture.now + 1000, fixture.now + 2000)
        fixture.register(self.tid, [('a', 'draw-a'), ('b', 'draw-b'), ('c', 'draw-c')])
        for person, team in [('roster-a', 'draw-a'), ('roster-b', 'draw-b')]:
            upload = self.upload(person, team, person)
            claim = R.claim_check(self.rt.flow.registry, upload['id'])
            R.record_verdict(self.rt.flow.registry, claim, verdict(BOT))
        jar = make_jar(fixture.root / 'fixture.jar', FILES)
        M.create_pool(self.rt.flow.store, 'staff-pool', M.load_engine_maps(jar), ENGINE, **GOOD)
        configured = override_settings(BIO_ENGINE_JAR=jar)
        configured.enable()
        self.addCleanup(configured.disable)

    def upload(self, person, team, key):
        actor = G.actor_for(self.rt.registration, person)
        return R.submit(self.rt.flow.registry, actor, team, self.tid, 'bot.py', BOT,
                        idempotency_key=key, deadline_at=self.fixture.now + 2000)

    def session(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.csrftoken = client.get('/api/v1/auth/session/').json()['csrf']
        return client

    def send(self, who, operation, message, *, method='POST', csrf=True):
        return who.generic(method, self.prefix + operation, json.dumps(message),
                           content_type='application/json', **({'HTTP_X_CSRFTOKEN': who.csrftoken} if csrf else {}))

    def tournament(self):
        return self.rt.tournaments.store.snapshot()['tournaments'][self.tid]

    def select(self, client):
        body = {'map_pool_id': 'staff-pool', 'expected_version': self.tournament()['version']}
        response = self.send(client, 'map-pool/', body, method='PUT')
        self.assertEqual(response.status_code, 200, response.content)
        return body

    def close_window(self):
        with self.rt.tournaments.store.transaction() as state:
            deadlines = state['tournaments'][self.tid]['deadlines']
            deadlines[T.REGISTRATION] = self.fixture.now - 2
            deadlines[T.SUBMISSION] = self.fixture.now - 1

    def draw(self, client):
        return self.send(client, 'bracket/generate/', {'confirm': True})

    def jobs(self):
        return [job for job in J.list_jobs(self.rt.flow.queue) if job['payload'].get('bracket_id') == self.tid]

    def test_map_selection_uses_scope_revisions_and_deadlines(self):
        organizer = self.session(self.org)
        available = organizer.get(self.prefix+'map-pool/')
        self.assertEqual(available.status_code, 200)
        self.assertIn('staff-pool', [item['id'] for item in available.json()['items']])
        saved = self.select(organizer)
        self.assertEqual(self.tournament()['map_pool_id'], 'staff-pool')
        self.assertEqual(self.send(organizer, 'map-pool/', saved, method='PUT').status_code, 409)
        participant = self.session(self.a)
        self.assertEqual(participant.get(self.prefix+'map-pool/').status_code, 403)
        self.assertEqual(self.send(participant, 'map-pool/', saved, method='PUT').status_code, 403)
        self.close_window()
        saved['expected_version'] = self.tournament()['version']
        self.assertEqual(self.send(organizer, 'map-pool/', saved, method='PUT').status_code, 409)

    def test_draw_refuses_early_unconfirmed_or_missing_catalogue_without_pinning(self):
        organizer = self.session(self.org)
        self.select(organizer)
        self.assertEqual(self.draw(organizer).status_code, 409)
        self.assertEqual(self.send(organizer, 'bracket/generate/', {'confirm': 1}).status_code, 400)
        self.close_window()
        with override_settings(BIO_ENGINE_JAR=None):
            self.assertEqual(self.draw(organizer).status_code, 503)
        self.assertNotIn(self.tid, self.rt.flow.registry.store.snapshot()['pins'])

    def test_pending_checks_and_changed_maps_refuse_without_pinning(self):
        organizer = self.session(self.org)
        self.select(organizer)
        changed = make_jar(self.fixture.root / 'changed.jar', {**FILES, GOOD['play'][0]: b'changed'})
        self.upload('roster-a', 'draw-a', 'unfinished-check')
        self.close_window()
        with override_settings(BIO_ENGINE_JAR=changed):
            response = self.draw(organizer)
        self.assertEqual(response.status_code, 409)
        self.assertIn('map pool', response.json()['error']['message'])
        response = self.draw(organizer)
        self.assertEqual(response.status_code, 409)
        self.assertIn('pending submission', response.json()['error']['message'])
        self.assertNotIn(self.tid, self.rt.flow.registry.store.snapshot()['pins'])

    def test_draw_stores_one_bracket_and_notices_without_starting_rounds(self):
        organizer = self.session(self.org)
        self.select(organizer)
        self.close_window()
        drawn = self.draw(organizer)
        self.assertEqual(drawn.status_code, 200, drawn.content)
        self.assertEqual(drawn.json()['excluded'], ['draw-c'])
        self.assertEqual(drawn.json()['bracket']['rounds'][0]['status'], B.READY)
        self.assertEqual(self.tournament()['status'], T.RUNNING)
        self.assertEqual(self.draw(organizer).json(), drawn.json())
        inbox = N.list_notifications(self.rt.notifications, R.Actor('roster-c', 'participant'))
        self.assertEqual(inbox['total'], 1)
        self.assertEqual(self.jobs(), [])

    def test_round_start_uses_confirmation_csrf_current_scope_and_one_job(self):
        admin = self.session(self.admin)
        organizer = self.session(self.org)
        self.select(organizer)
        self.close_window()
        self.assertEqual(self.draw(admin).status_code, 200)
        start = 'rounds/1/start/'
        body = {'confirm': True, 'idempotency_key': 'start-round'}
        self.assertEqual(self.send(organizer, start, body, csrf=False).status_code, 403)
        self.assertEqual(self.send(self.session(self.a), start, body).status_code, 403)
        response = self.send(organizer, start, body)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.send(organizer, start, body).json(), response.json())
        self.assertEqual(self.send(organizer, 'rounds/2/start/', body).status_code, 409)
        self.assertEqual(self.send(admin, start, {'confirm': True, 'idempotency_key': 'admin-retry'}).json(), response.json())
        self.assertEqual(len(self.jobs()), 1)
        OrganizerAssignment.objects.filter(user=self.org, tournament_id=self.tid).update(active=False)
        self.assertEqual(self.send(organizer, start, body).status_code, 404)

    def test_paused_round_cannot_be_requeued_through_start(self):
        organizer = self.session(self.org)
        self.select(organizer)
        self.close_window()
        self.assertEqual(self.draw(organizer).status_code, 200)
        B.start_round(self.rt.flow.store, self.tid, 1, 'fixture-organizer')
        outcome = B.run_round(self.rt.flow.store, self.tid, 1, lambda context: PLATFORM, sleep=lambda seconds: None)
        self.assertEqual(outcome['status'], B.PAUSED)
        body = {'confirm': True, 'idempotency_key': 'paused-round'}
        self.assertEqual(self.send(organizer, 'rounds/1/start/', body).status_code, 409)
        self.assertEqual(self.jobs(), [])

    def test_round_start_can_retry_after_restoring_the_pinned_maps(self):
        organizer = self.session(self.org)
        self.select(organizer)
        self.close_window()
        self.assertEqual(self.draw(organizer).status_code, 200)
        changed = make_jar(self.fixture.root / 'changed.jar', {**FILES, GOOD['play'][0]: b'changed'})
        start = 'rounds/1/start/'
        body = {'confirm': True, 'idempotency_key': 'start-after-map-repair'}

        with override_settings(BIO_ENGINE_JAR=changed):
            response = self.send(organizer, start, body)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn('pinned map pool', response.json()['error']['message'])
        with override_settings(BIO_ENGINE_JAR=None):
            self.assertEqual(self.send(organizer, start, body).status_code, 503)
        self.assertEqual(B.get_bracket(self.rt.flow.store, self.tid)['rounds'][0]['status'], B.READY)
        self.assertEqual(self.jobs(), [])

        self.assertEqual(self.send(organizer, start, body).status_code, 200)
        self.assertEqual(len(self.jobs()), 1)
