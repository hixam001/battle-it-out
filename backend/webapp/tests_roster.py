# SPDX-License-Identifier: AGPL-3.0-only
"""Role-scoped roster import, correction and exclusion reports."""
import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from backend.registration import registration as G
from backend.tournaments import tournaments as T
from . import tests as fixtures
from .models import OrganizerAssignment


ROOT = '/api/v1/tournaments/editing/roster/'
ROW = {'email': 'new@uni.edu', 'team_key': 'new-team', 'team_name': 'New team',
       'member_number': 1, 'role': 'captain'}
CSV = b'email,team_key,team_name,member_number,role\nnew@uni.edu,new-team,New team,1,captain\n'


class RosterAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.FeatureAPI.setUpTestData.__func__(cls)
        OrganizerAssignment.objects.create(user=cls.org, tournament_id='editing')

    def setUp(self):
        fixture = fixtures.FeatureAPI()
        fixture.a = self.a
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.rt = fixture.rt
        self.now = fixture.now
        fixture.make_cup('editing', self.now + 2000, self.now + 3000)
        fixture.make_cup('foreign', self.now + 2000, self.now + 3000)

    def session(self, user):
        browser = Client(enforce_csrf_checks=True)
        if user:
            browser.force_login(user)
        token = browser.get('/api/v1/auth/session/').json()['csrf']
        return browser, token

    def import_rows(self, session, rows, *, key='roster-once', csrf=True):
        browser, token = session
        headers = {'HTTP_X_CSRFTOKEN': token} if csrf else {}
        return browser.post(ROOT + 'import/', json.dumps({'rows': rows}), content_type='application/json',
                            HTTP_IDEMPOTENCY_KEY=key, **headers)

    def import_csv(self, session, raw=CSV, *, key='roster-once'):
        browser, token = session
        return browser.post(ROOT + 'import/', {'file': SimpleUploadedFile('original.csv', raw)},
                            HTTP_X_CSRFTOKEN=token, HTTP_IDEMPOTENCY_KEY=key)

    def correct(self, session, entry_id, data, *, root=ROOT):
        browser, token = session
        return browser.patch(root + entry_id + '/', json.dumps(data), content_type='application/json',
                             HTTP_X_CSRFTOKEN=token)

    def test_admin_json_import_records_redacted_partial_results_and_retry(self):
        admin = self.session(self.admin)
        rows = [ROW, {**ROW, 'email': 'other@uni.edu', 'member_number': '9' * 5000},
                {**ROW, 'fixture-private': 'ignored'}]
        first = self.import_rows(admin, rows)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()['created'], 1)
        self.assertEqual([r['row'] for r in first.json()['rejected']], [2, 3])
        self.assertNotIn('fixture-private', first.content.decode())
        before = self.rt.registration.store.snapshot()
        self.assertEqual(self.import_rows(admin, rows).json(), first.json())
        self.assertEqual(self.import_rows(admin, [ROW]).status_code, 409)
        self.assertEqual(self.rt.registration.store.snapshot(), before)
        self.assertEqual(len(before['tournaments']['editing']['batches']), 1)
        self.assertNotIn('original.csv', str(before['tournaments']['editing']))

    def test_organizer_csv_import_requires_current_scope_and_csrf(self):
        organizer = self.session(self.org)
        self.assertEqual(self.import_rows(organizer, [ROW], csrf=False).status_code, 403)
        self.assertEqual(self.import_csv(self.session(None)).status_code, 401)
        for user in (self.a, self.outsider):
            self.assertEqual(self.import_rows(self.session(user), [ROW]).status_code, 404)
        visible_participant = self.session(self.a)[0].get('/api/v1/tournaments/cup/roster/')
        self.assertEqual(visible_participant.status_code, 403)
        first = self.import_csv(organizer)
        self.assertEqual(first.status_code, 200, first.content)
        roster = organizer[0].get(ROOT).json()['items']
        self.assertEqual(roster[0]['email'], ROW['email'])
        self.assertNotIn('code_id', roster[0])
        OrganizerAssignment.objects.filter(user=self.org, tournament_id='editing').update(active=False)
        self.assertEqual(self.import_csv(organizer).status_code, 404)
        self.assertEqual(organizer[0].get(ROOT + 'report/').status_code, 404)

    def test_correction_requires_current_version_and_cannot_change_claimed_entry(self):
        staff = self.session(self.org)
        self.assertEqual(self.import_csv(staff).status_code, 200)
        entry = staff[0].get(ROOT).json()['items'][0]
        entry_id = entry['id']
        new = self.correct(staff, entry_id, {'expected_version': entry['version'], 'team_name': 'Updated team'})
        self.assertEqual(new.status_code, 200, new.content)
        self.assertEqual(new.json()['team_name'], 'Updated team')
        self.assertEqual(new.json()['version'], entry['version'] + 1)
        self.assertEqual(self.correct(staff, entry_id, {'expected_version': entry['version'], 'team_name': 'Stale'})
                         .status_code, 409)
        self.assertEqual(self.correct(staff, entry_id, {'expected_version': True, 'team_name': 'Bad'})
                         .status_code, 400)
        codes = G.issue_codes(self.rt.registration, fixtures.ADM, 'editing')['issued']
        G.claim(self.rt.registration, 'editing', ROW['email'], codes[0]['code'], 'roster-new')
        claimed = staff[0].get(ROOT).json()['items'][0]
        result = self.correct(staff, entry_id, {'expected_version': claimed['version'], 'team_name': 'Locked'})
        self.assertEqual(result.status_code, 409)
        foreign = self.correct(self.session(self.admin), entry_id, {'expected_version': 1, 'team_name': 'Odd'},
                               root=ROOT.replace('/editing/', '/foreign/'))
        self.assertEqual(foreign.status_code, 404)

    def test_staff_report_lists_exclusions_after_the_stored_deadline(self):
        admin = self.session(self.admin)
        self.assertEqual(self.import_rows(admin, [ROW]).status_code, 200)
        entry = admin[0].get(ROOT).json()['items'][0]
        self.assertEqual(admin[0].get(ROOT + 'report/').json()['excluded'], [])
        with self.rt.tournaments.store.transaction() as state:
            state['tournaments']['editing']['deadlines'][T.REGISTRATION] = self.now - 1
        response = admin[0].get(ROOT + 'report/')
        result = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(result['closed'])
        self.assertEqual(result['excluded'], [entry['id']])
        self.assertEqual(result['counts'][G.UNREGISTERED], 1)
        self.assertNotIn(ROW['email'], response.content.decode())
        self.assertEqual(self.import_rows(admin, [{**ROW, 'team_name': 'Late'}], key='late').status_code, 409)
        self.assertEqual(self.import_rows(admin, [ROW]).status_code, 200)

    def test_malformed_and_oversized_uploads_do_not_change_roster(self):
        admin = self.session(self.admin)
        browser, token = admin
        before = self.rt.registration.store.snapshot()
        for response, status in (
            (self.import_csv(admin, b'\xff'), 400),
            (self.import_csv(admin, b'wrong,header\n'), 400),
            (self.import_csv(admin, b'a' * (G.MAX_CSV_BYTES + 1)), 413),
            (self.import_rows(admin, [{**ROW, 'team_name': 'x' * G.MAX_CSV_BYTES}]), 413),
            (self.import_rows(admin, [ROW], key=''), 400),
            (browser.post(ROOT + 'import/', 'plain', content_type='text/plain',
                          HTTP_X_CSRFTOKEN=token, HTTP_IDEMPOTENCY_KEY='plain'), 415),
        ):
            self.assertEqual(response.status_code, status, response.content)
            self.assertEqual(response.json()['error']['request_id'], response['X-Request-ID'])
        self.assertEqual(self.rt.registration.store.snapshot(), before)
