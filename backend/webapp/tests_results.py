# SPDX-License-Identifier: AGPL-3.0-only
"""Scoped bracket/game reads backed by the same state the workers record."""
from django.test import Client, TestCase

from backend.match_orchestrator import bracket as B, orchestrator as O
from backend.match_orchestrator.tests.test_bracket import MAPS, teams
from backend.match_orchestrator.tests.test_tiebreak import COIN, PLATFORM, Coin, won
from backend.tournaments import tournaments as T
from .models import Identity, OrganizerAssignment
from .tests import FeatureAPI


class ResultsAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        FeatureAPI.setUpTestData.__func__(cls)

    def setUp(self):
        self.fixture = FeatureAPI()
        self.fixture.a = self.a
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.rt = self.fixture.rt
        self.store = self.rt.flow.store
        self.mid = self.store.snapshot()['series'][self.fixture.sid]['games'][0]['match_id']
        self.bracket_url = '/api/v1/tournaments/cup/bracket/'
        self.match_url = self.match_path(self.mid)

    def reader(self, user):
        client = Client()
        client.force_login(user)
        return client

    def match_path(self, match_id):
        return f'/api/v1/matches/{match_id}/'

    def make_bracket(self, tid, bid, entries, **options):
        self.fixture.make_cup(tid, self.fixture.now + 1000, self.fixture.now + 2000)
        B.create_bracket(self.store, bid, entries, MAPS, **options)
        with self.store.transaction() as data:
            data['brackets'][bid]['tournament_id'] = tid

    def assert_hidden(self, response):
        self.assertEqual(response.status_code, 404)
        error = response.json()['error']
        self.assertEqual(error.pop('request_id'), response['X-Request-ID'])
        self.assertEqual(error['code'], 'NOT_FOUND')
        return error

    def test_current_roles_read_the_same_recorded_winner_and_version_refs(self):
        before = self.store.snapshot()
        for user in (self.a, self.b, self.org, self.admin):
            with self.subTest(user=user.username):
                client = self.reader(user)
                response = client.get(self.bracket_url)
                self.assertEqual(response.status_code, 200)
                record = response.json()['bracket']
                self.assertEqual(record['champion'], 'ta')
                self.assertEqual(record['map_pool_id'], 'pool')
                self.assertEqual(record['maps'], {
                    'play': ['one'], 'tiebreak_normal': ['two'], 'tiebreak_final': ['two', 'three', 'four'],
                })
                self.assertNotIn('sha256', response.content.decode())
                decision = record['rounds'][0]['matches'][0]
                self.assertEqual(decision['winner'], 'ta')
                self.assertEqual(decision['series']['games'], [{'match_id': self.mid, 'status': O.COMPLETED}])
                self.assertEqual(sum(decision['series']['wins'].values()), 1)

                response = client.get(self.match_url)
                self.assertEqual(response['Cache-Control'], 'private, no-store')
                self.assertEqual(response.status_code, 200)
                match = response.json()
                self.assertEqual(match['match_id'], self.mid)
                self.assertEqual(match['round_number'], 1)
                self.assertEqual(match['series']['result']['winner_team'], 'ta')
                self.assertEqual(sorted(match['series']['versions'].values()), ['ta-v1', 'tb-v1'])
                self.assertNotIn('/x/', response.content.decode())
                self.assertNotIn('has_replay', response.content.decode())
                self.assertNotIn('structured_log', response.content.decode())
                self.assertNotIn('sha256', response.content.decode())
        self.assertEqual(self.store.snapshot(), before)

    def test_anonymous_and_outside_scope_are_refused(self):
        for url in (self.bracket_url, self.match_url):
            self.assertEqual(Client().get(url).status_code, 401)
        outsider = self.reader(self.outsider)
        self.assertEqual(self.assert_hidden(outsider.get(self.bracket_url)),
                         self.assert_hidden(outsider.get('/api/v1/tournaments/absent/bracket/')))
        self.assertEqual(self.assert_hidden(outsider.get(self.match_url)),
                         self.assert_hidden(outsider.get(self.match_path('absent'))))
        self.assert_hidden(self.reader(self.admin).get(self.match_path(self.fixture.sid)))

    def test_scope_revocation_applies_on_the_next_request(self):
        organizer = self.reader(self.org)
        participant = self.reader(self.a)
        self.assertEqual(organizer.get(self.bracket_url).status_code, 200)
        self.assertEqual(participant.get(self.match_url).status_code, 200)
        OrganizerAssignment.objects.filter(user=self.org).update(active=False)
        Identity.objects.filter(user=self.a).update(roster_user_id='unlinked')
        self.assert_hidden(organizer.get(self.bracket_url))
        self.assert_hidden(participant.get(self.match_url))

    def test_archived_history_survives_while_deleted_tournament_is_hidden(self):
        admin = self.reader(self.admin)
        before = [admin.get(url).json() for url in (self.bracket_url, self.match_url)]
        with self.rt.tournaments.store.transaction() as state:
            state['tournaments']['cup']['status'] = T.ARCHIVED
        self.assertEqual([admin.get(url).json() for url in (self.bracket_url, self.match_url)], before)
        with self.rt.tournaments.store.transaction() as state:
            state['tournaments']['cup']['status'] = T.DELETED
        self.assert_hidden(admin.get(self.bracket_url))
        self.assert_hidden(admin.get(self.match_url))

    def test_pending_draw_byes_and_unfilled_slots_come_from_bracket(self):
        self.fixture.make_cup('pending', self.fixture.now + 1000, self.fixture.now + 2000)
        admin = self.reader(self.admin)
        self.assertEqual(admin.get('/api/v1/tournaments/pending/bracket/').json(),
                         {'tournament_id': 'pending', 'bracket': None})

        self.make_bracket('byes', 'alternate-id', teams(3))
        bracket = admin.get('/api/v1/tournaments/byes/bracket/').json()['bracket']
        self.assertEqual(bracket['id'], 'alternate-id')
        self.assertEqual(bracket['draw']['byes'], 1)
        first = bracket['rounds'][0]
        bye = next(item for item in first['matches'] if item['bye'])
        self.assertEqual(bye['winner'], bye['a'])
        self.assertIsNone(bye['series'])
        final = bracket['rounds'][1]
        self.assertEqual(final['status'], B.PENDING)
        self.assertIsNone(final['matches'][0]['b'])

    def test_tiebreak_games_and_recorded_coin_flip_are_stable_on_repeat_reads(self):
        self.make_bracket('tied-cup', 'tied-cup', teams(2))
        B.start_round(self.store, 'tied-cup', 1, 'org')
        coin = Coin('B')
        played = B.run_round(self.store, 'tied-cup', 1, lambda ctx: won('A', reason=COIN), coin=coin)
        self.assertEqual(played['status'], B.COMPLETED)
        admin = self.reader(self.admin)
        bracket = admin.get('/api/v1/tournaments/tied-cup/bracket/').json()['bracket']
        game_refs = bracket['rounds'][0]['matches'][0]['series']['games']
        self.assertEqual(len(game_refs), 4)
        path = self.match_path(game_refs[-1]['match_id'])
        series = admin.get(path).json()['series']
        self.assertEqual([game['map'] for game in series['games'][1:]], MAPS['tiebreak_final'])
        self.assertTrue(all(game['winner_team'] is None for game in series['games']))
        self.assertEqual(series['wins'], {'A': 0, 'B': 0})
        self.assertEqual(series['result']['result_type'], 'coin_flip')
        self.assertEqual(series['result']['winner_team'], series['coin_flip']['result_team'])
        self.assertEqual(series['coin_flip']['probability_each'], 0.5)
        self.assertFalse(series['coin_flip']['rerolls_allowed'])
        self.assertEqual(admin.get(path).json()['series'], series)
        self.assertEqual(coin.calls, 1)

    def test_paused_game_is_visible_without_publishing_a_result(self):
        self.make_bracket('paused-cup', 'paused-cup', teams(2), max_attempts=1)
        B.start_round(self.store, 'paused-cup', 1, 'org')
        outcome = B.run_round(self.store, 'paused-cup', 1, lambda ctx: PLATFORM)
        self.assertEqual(outcome['status'], B.PAUSED)
        admin = self.reader(self.admin)
        bracket = admin.get('/api/v1/tournaments/paused-cup/bracket/').json()['bracket']
        match = bracket['rounds'][0]['matches'][0]
        self.assertIsNone(match['winner'])
        game = match['series']['games'][0]
        self.assertEqual(game['status'], O.PAUSED)
        series = admin.get(self.match_path(game['match_id'])).json()['series']
        self.assertIsNone(series['result'])
        self.assertIsNone(series['coin_flip'])
