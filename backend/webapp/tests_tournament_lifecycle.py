# SPDX-License-Identifier: AGPL-3.0-only
"""Tournament lifecycle through session-authenticated HTTP and the shared stores."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client, TestCase, override_settings

from backend.tournaments import tournaments as T
from . import domain as D
from .models import AuditEvent, Identity, OrganizerAssignment


class TournamentLifecycleAPI(TestCase):
    collection = '/api/v1/tournaments/'

    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.admin = users.create_superuser('admin', email='admin@example.org')
        cls.organizer = users.create_user('creator')
        cls.other = users.create_user('other-organizer')
        cls.participant = users.create_user('participant')
        for user in (cls.organizer, cls.other):
            Identity.objects.create(user=user, role='organizer')

    def setUp(self):
        root = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(BIO_DATA_DIR=Path(root)))
        self.store = D.runtime().tournaments.store
        tomorrow = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
        self.draft = {'name': 'Contest', 'description': 'Draft description',
                      'registration_deadline': tomorrow.isoformat(),
                      'submission_deadline': (tomorrow + timedelta(days=1)).isoformat()}

    def session(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.csrf = client.get('/api/v1/auth/session/').json()['csrf']
        return client

    def send(self, client, path, data, *, method='POST', key='draft-key', csrf=True):
        headers = {'Idempotency-Key': key}
        if csrf:
            headers['X-CSRFToken'] = client.csrf
        return client.generic(method, path, json.dumps(data), content_type='application/json', headers=headers)

    def create(self, client):
        response = self.send(client, self.collection, self.draft)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def change(self, client, path, version, status, **data):
        response = self.send(client, path, {'expected_version': version, **data})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['status'], status)
        self.assertEqual(response.json()['version'], version + 1)
        return response.json()

    def test_create_retries_preserve_one_draft_assignment_and_audit(self):
        creator = self.session(self.organizer)
        draft = self.create(creator)
        tid = draft['id']
        self.assertEqual(self.create(creator), draft)
        response = self.send(creator, self.collection, {**self.draft, 'name': 'Different'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(OrganizerAssignment.objects.filter(user=self.organizer, tournament_id=tid).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(tournament_id=tid, action='organizer_assigned').count(), 1)
        self.assertEqual([row['action'] for row in self.store.snapshot()['audit']], ['create'])
        self.assertEqual(creator.get(self.collection).json()['items'][0]['id'], tid)
        self.assertEqual(creator.get(f'{self.collection}{tid}/').json(), draft)
        OrganizerAssignment.objects.filter(user=self.organizer, tournament_id=tid).update(active=False)
        self.assertEqual(creator.get(self.collection).json()['items'], [])
        self.assertEqual(creator.get(f'{self.collection}{tid}/').status_code, 404)
        self.assertEqual(self.send(creator, self.collection, self.draft).status_code, 404)
        self.assertFalse(OrganizerAssignment.objects.filter(tournament_id=tid, active=True).exists())

    def test_approval_rejection_version_and_manual_registration(self):
        creator, admin = self.session(self.organizer), self.session(self.admin)
        path = f"{self.collection}{self.create(creator)['id']}/"
        self.assertEqual(self.send(admin, path+'approve/', {'expected_version': 1, 'confirm': True}).status_code, 409)
        self.change(creator, path+'submit-for-approval/', 1, T.PENDING)
        self.assertEqual(self.send(creator, path, {'expected_version': 2, 'name': 'Blocked'}, method='PATCH').status_code, 409)
        reason = 'Update the schedule description.'
        rejected = self.change(admin, path+'reject/', 2, T.REJECTED, reason=reason)
        self.assertEqual(rejected['rejection_reason'], reason)
        updated = self.send(creator, path, {'expected_version': 3, 'name': 'Updated contest'}, method='PATCH')
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()['version'], 4)
        self.change(creator, path+'submit-for-approval/', 4, T.PENDING)
        stale = self.send(admin, path+'approve/', {'expected_version': 2, 'confirm': True})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.send(admin, path+'approve/', {'expected_version': 5, 'confirm': 1}).status_code, 400)
        self.change(admin, path+'approve/', 5, T.APPROVED, confirm=True)
        self.change(creator, path+'open-registration/', 6, T.OPEN)
        self.assertEqual(self.send(creator, path+'open-registration/', {'expected_version': 6}).status_code, 409)

    def test_retry_repairs_assignment_after_postgres_rollback(self):
        creator = self.session(self.organizer)
        with transaction.atomic():
            draft = self.create(creator)
            transaction.set_rollback(True)
        self.assertIn(draft['id'], self.store.snapshot()['tournaments'])
        self.assertFalse(OrganizerAssignment.objects.exists())
        self.assertEqual(self.create(creator), draft)
        self.assertEqual(OrganizerAssignment.objects.filter(tournament_id=draft['id'], active=True).count(), 1)
        self.assertEqual(AuditEvent.objects.filter(tournament_id=draft['id']).count(), 1)
        self.assertEqual([row['action'] for row in self.store.snapshot()['audit']], ['create'])

    def test_access_csrf_and_invalid_deadlines_roll_back_assignment(self):
        creator = self.session(self.organizer)
        participant = self.session(self.participant)
        other = self.session(self.other)
        self.assertEqual(self.send(creator, self.collection, self.draft, csrf=False).status_code, 403)
        self.assertEqual(self.send(participant, self.collection, self.draft).status_code, 403)
        invalid = {**self.draft, 'registration_deadline': '2000-01-01T00:00:00Z'}
        self.assertEqual(self.send(creator, self.collection, invalid).status_code, 400)
        self.assertFalse(OrganizerAssignment.objects.exists())
        self.assertFalse(AuditEvent.objects.exists())
        draft = self.create(creator)
        path = f"{self.collection}{draft['id']}/"
        self.assertEqual(other.get(path).status_code, 404)
        self.assertEqual(participant.get(path).status_code, 404)
        self.assertEqual(self.send(other, path, {'name': 'Foreign', 'expected_version': 1}, method='PATCH').status_code, 404)
        OrganizerAssignment.objects.create(user=self.other, tournament_id=draft['id'])
        self.assertEqual(self.send(other, path+'submit-for-approval/', {'expected_version': 1}).status_code, 403)
        self.assertEqual(self.send(other, path+'approve/', {'expected_version': 1, 'confirm': True}).status_code, 403)

    def test_admin_draft_can_be_approved_directly_then_uses_deadline_lock(self):
        admin = self.session(self.admin)
        draft = self.create(admin)
        path = f"{self.collection}{draft['id']}/"
        self.assertEqual(draft['created_by_role'], 'admin')
        self.assertFalse(OrganizerAssignment.objects.exists())
        self.change(admin, path+'approve/', 1, T.APPROVED, confirm=True)
        with self.store.transaction() as state:
            state['tournaments'][draft['id']]['deadlines'][T.SUBMISSION] = 1
        response = self.send(admin, path, {'expected_version': 2, 'description': 'Locked'}, method='PATCH')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(admin.get(path).json()['description'], self.draft['description'])
