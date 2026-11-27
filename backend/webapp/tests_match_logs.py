# SPDX-License-Identifier: AGPL-3.0-only
"""Read only the current role's verified structured match log."""
from django.test import Client, TestCase

from backend.match_runner import match_log as L
from backend.tournaments import tournaments as T
from . import tests as fixtures
from .models import OrganizerAssignment


class MatchLogsAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.FeatureAPI.setUpTestData.__func__(cls)

    def setUp(self):
        fixture = fixtures.FeatureAPI()
        fixture.a = self.a
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.rt = fixture.rt
        self.root = fixture.root
        state = self.rt.flow.store.snapshot()
        self.mid = state['series'][fixture.sid]['games'][0]['match_id']
        self.match = state['matches'][self.mid]
        self.path = f'/api/v1/matches/{self.mid}/logs/'
        self.file = self.publish()

    def publish(self, number=1, *, log_match=None):
        if number == 1:
            trace = self.match['attempts'][0]['trace_id']
        else:
            trace = L.new_trace_id()
        ctx = {
            'trace_id': trace, 'match_id': log_match or self.mid, 'attempt': number,
            'teams': {'A': self.match['team_a'], 'B': self.match['team_b']},
            'submissions': {'A': self.match['submission_a'], 'B': self.match['submission_b']},
            'engine_version': '1.2.6', 'map': self.match['map'],
            'started_at': '2026-11-27T10:00:00Z', 'finished_at': '2026-11-27T10:00:05Z',
        }
        result = {'winner': 'A', 'loser': 'B', 'classification': 'normal', 'kind': 'score',
                  'outcome': 'completed', 'reason': 'Won on points', 'round': 1,
                  'router': {'path': str(self.root / 'private-router')}, 'replay': True}
        events = L.build_events(result, ctx, '[A: #5@1] First side output\n[B: #6@1] Second side output\n')
        path = self.root / 'out' / 'matches' / self.mid / f'attempt-{number}' / 'match-20261127-100005.events.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        report = L.write_jsonl(path, events)
        with self.rt.flow.store.transaction() as state:
            attempts = state['matches'][self.mid]['attempts']
            if number == 1:
                attempts[0]['summary']['structured_log'] = report
            else:
                attempts.append({**attempts[0], 'number': number, 'trace_id': trace,
                                 'summary': {**attempts[0]['summary'], 'structured_log': report}})
        return path

    def session(self, user):
        browser = Client()
        if user:
            browser.force_login(user)
        return browser

    def get(self, user, suffix=''):
        return self.session(user).get(self.path + suffix)

    def test_teams_see_only_their_own_output_and_public_metadata(self):
        for team_id, user in (('ta', self.a), ('tb', self.b)):
            response = self.get(user)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            expected_side = 'A' if self.match['team_a'] == team_id else 'B'
            items = response.json()['items']
            self.assertEqual({item['visibility'] for item in items}, {'all', f'team:{expected_side}'})
            output = next(item for item in items if item['event'] == 'team.output')
            self.assertEqual(output['data']['entries'][0]['text'],
                             'First side output' if expected_side == 'A' else 'Second side output')
            self.assertNotIn('replay_available', response.content.decode())

    def test_assigned_organizer_reads_both_teams_and_admin_gets_safe_diagnostics(self):
        org = self.get(self.org)
        admin = self.get(self.admin)
        self.assertEqual(org.status_code, 200)
        self.assertEqual(admin.status_code, 200)
        self.assertEqual({item['visibility'] for item in org.json()['items']}, {'all', 'team:A', 'team:B'})
        diagnostics = next(item for item in admin.json()['items'] if item['visibility'] == 'staff')
        self.assertEqual(diagnostics['data']['classification_kind'], 'score')
        self.assertNotIn('router', diagnostics['data'])
        self.assertNotIn(str(self.root), admin.content.decode())

    def test_current_scope_and_archive_status_are_enforced(self):
        self.assertEqual(self.get(None).status_code, 401)
        self.assertEqual(self.get(self.outsider).status_code, 404)
        org = self.session(self.org)
        self.assertEqual(org.get(self.path).status_code, 200)
        OrganizerAssignment.objects.filter(user=self.org, tournament_id='cup').update(active=False)
        self.assertEqual(org.get(self.path).status_code, 404)
        with self.rt.tournaments.store.transaction() as state:
            state['tournaments']['cup']['status'] = T.ARCHIVED
        self.assertEqual(self.get(self.a).status_code, 200)
        with self.rt.tournaments.store.transaction() as state:
            state['tournaments']['cup']['status'] = T.DELETED
        self.assertEqual(self.get(self.admin).status_code, 404)

    def test_attempt_option_selects_verified_history(self):
        self.publish(2)
        self.assertEqual(self.get(self.a).json()['attempt'], 2)
        self.assertEqual(self.get(self.a, '?attempt=1').json()['attempt'], 1)
        self.assertEqual(self.get(self.a, '?attempt=3').status_code, 404)
        for query in ('?attempt=0', '?attempt=101', '?attempt=1&attempt=2', '?path=worker'):
            self.assertEqual(self.get(self.a, query).status_code, 400)

    def test_tamper_or_wrong_attempt_receives_safe_unavailable_response(self):
        self.file.write_bytes(self.file.read_bytes().replace(b'First side', b'Other side', 1))
        for case in ('changed-bytes', 'wrong-match'):
            with self.subTest(case=case):
                if case == 'wrong-match':
                    self.publish(log_match='different-match')
                response = self.get(self.admin)
                self.assertEqual(response.status_code, 503, response.content)
                self.assertEqual(response.json()['error']['code'], 'SERVICE_UNAVAILABLE')
                self.assertNotIn(str(self.root), response.content.decode())

    def test_existing_metadata_does_not_allow_following_a_file_link(self):
        outside = self.root / 'separate.jsonl'
        self.file.rename(outside)
        self.file.symlink_to(outside)
        self.assertEqual(self.get(self.admin).status_code, 503)

    def test_old_attempt_without_log_metadata_is_missing(self):
        with self.rt.flow.store.transaction() as state:
            state['matches'][self.mid]['attempts'][0]['summary'].pop('structured_log')
        self.assertEqual(self.get(self.a).status_code, 404)
