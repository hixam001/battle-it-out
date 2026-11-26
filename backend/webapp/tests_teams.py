# SPDX-License-Identifier: AGPL-3.0-only
"""Private team profile from the authoritative verified roster."""
from django.test import Client, TestCase

from backend.registration import registration as G
from backend.tournaments import tournaments as T
from . import tests as fixtures
from .models import OrganizerAssignment


PROFILE = '/api/v1/tournaments/second-cup/teams/second-team/'


class TeamProfileAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.FeatureAPI.setUpTestData.__func__(cls)
        OrganizerAssignment.objects.create(user=cls.org, tournament_id='second-cup')

    def setUp(self):
        fixture = fixtures.FeatureAPI()
        fixture.a = self.a
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.rt = fixture.rt
        fixture.make_cup('second-cup', fixture.now + 1000, fixture.now + 2000)
        rows = [
            {'email': name + '@uni.edu', 'team_key': 'second-team', 'team_name': 'Second team',
             'member_number': number, 'role': role}
            for name, number, role in (('b', 2, 'member'), ('a', 1, 'captain'))
        ]
        G.import_roster(self.rt.registration, fixtures.ADM, 'second-cup', rows)
        roster = G.list_roster(self.rt.registration, fixtures.ADM, 'second-cup')
        self.entries = {entry['email'].split('@')[0]: entry for entry in roster}
        issued = G.issue_codes(self.rt.registration, fixtures.ADM, 'second-cup')['issued']
        codes = {item['entry_id']: item['code'] for item in issued}
        for name, entry in self.entries.items():
            G.claim(self.rt.registration, 'second-cup', entry['email'], codes[entry['id']], 'roster-' + name)
        G.confirm_email(self.rt.registration, 'second-cup', 'roster-a')

    def session(self, user):
        client = Client()
        if user is not None:
            client.force_login(user)
        return client

    @staticmethod
    def error(response):
        return {key: value for key, value in response.json()['error'].items() if key != 'request_id'}

    def test_only_verified_members_appear_in_slot_order_without_personal_fields(self):
        browser = self.session(self.a)
        response = browser.get(PROFILE)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(response.json(), {
            'id': 'second-team', 'tournament_id': 'second-cup', 'name': 'Second team',
            'members': [{'member_number': 1, 'role_label': 'captain', 'is_captain': True}],
        })
        self.assertEqual(self.session(self.b).get(PROFILE).status_code, 404)
        G.confirm_email(self.rt.registration, 'second-cup', 'roster-b')
        self.assertEqual(browser.get(PROFILE).json()['members'], [
            {'member_number': 1, 'role_label': 'captain', 'is_captain': True},
            {'member_number': 2, 'role_label': 'member', 'is_captain': False},
        ])
        self.assertEqual(self.session(self.b).get(PROFILE).status_code, 200)

    def test_cross_team_tournament_and_missing_ids_are_hidden(self):
        participant = self.session(self.a)
        missing = participant.get(PROFILE.replace('second-team/', 'missing/'))
        other_tournament = participant.get(PROFILE.replace('second-cup/', 'cup/'))
        other_team = participant.get('/api/v1/tournaments/cup/teams/tb/')
        for response in (missing, other_tournament, other_team, self.session(self.outsider).get(PROFILE)):
            self.assertEqual(response.status_code, 404, response.content)
            self.assertEqual(self.error(response), self.error(missing))
        self.assertEqual(self.session(None).get(PROFILE).status_code, 401)

    def test_current_staff_scope_and_archive_boundary(self):
        org = self.session(self.org)
        admin = self.session(self.admin)
        self.assertEqual(org.get(PROFILE).json(), admin.get(PROFILE).json())
        with self.rt.tournaments.store.transaction() as state:
            state['tournaments']['second-cup']['status'] = T.ARCHIVED
        self.assertEqual(self.session(self.a).get(PROFILE).status_code, 200)
        self.assertEqual(org.get(PROFILE).status_code, 200)
        OrganizerAssignment.objects.filter(user=self.org, tournament_id='second-cup').update(active=False)
        self.assertEqual(org.get(PROFILE).status_code, 404)
        with self.rt.tournaments.store.transaction() as state:
            state['tournaments']['second-cup']['status'] = T.DELETED
        self.assertEqual(admin.get(PROFILE).status_code, 404)

    def test_existing_roster_size_and_claimed_name_rules_apply(self):
        roster = self.rt.registration
        slots = [
            {'email': f'{number}@uni.edu', 'team_key': 'second-team', 'team_name': 'Second team',
             'member_number': number, 'role': 'member'}
            for number in range(3, G.MAX_TEAM_SIZE + 2)
        ]
        batch = G.import_roster(roster, fixtures.ADM, 'second-cup', slots)
        self.assertEqual((batch['created'], len(batch['rejected'])), (G.MAX_TEAM_SIZE - 2, 1))
        with self.assertRaises(G.Locked):
            G.correct_entry(roster, fixtures.ADM, 'second-cup', self.entries['a']['id'], {'team_name': 'Rename'})
        admin = self.session(self.admin)
        self.assertEqual(admin.patch(PROFILE, {'name': 'Rename'}).status_code, 405)
        self.assertEqual(admin.get(PROFILE).json()['name'], 'Second team')
