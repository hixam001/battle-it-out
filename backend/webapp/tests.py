# SPDX-License-Identifier: AGPL-3.0-only
"""HTTP/CSRF/privacy, analytics and dispute transactions against real PostgreSQL."""
import io
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.test import TestCase, Client, override_settings
from rest_framework.test import APIClient
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.match_orchestrator import bracket as B, maps as M
from backend.match_orchestrator.tests.test_bracket import lower_wins
from backend.tournament_flow import flow as F
from backend.tournaments import tournaments as T
from backend.work_queue import jobs as J
from backend.work_queue.tests.test_handlers import verdict
from . import domain as D
from .models import Identity, OrganizerAssignment, Dispute, AuditEvent, LoginAttempt, Receipt

BOT=b'def turn():\n    pass\n'
ADM=R.Actor('staff','admin')

class FeatureAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        U=get_user_model()
        cls.a=U.objects.create_user('captain-a',email='a@uni.edu',password='test-fixture-passphrase')
        cls.b=U.objects.create_user('captain-b',email='b@uni.edu',password='test-fixture-passphrase')
        cls.org=U.objects.create_user('organizer',password='test-fixture-passphrase')
        cls.admin=U.objects.create_superuser('admin',email='admin@example.org',password='test-fixture-passphrase')
        cls.outsider=U.objects.create_user('outsider',password='test-fixture-passphrase')
        Identity.objects.create(user=cls.a,role='participant',roster_user_id='roster-a')
        Identity.objects.create(user=cls.b,role='participant',roster_user_id='roster-b')
        Identity.objects.create(user=cls.org,role='organizer')
        OrganizerAssignment.objects.create(user=cls.org,tournament_id='cup')
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.override=override_settings(BIO_DATA_DIR=self.root);self.override.enable()
        self.addCleanup(self.tmp.cleanup);self.addCleanup(self.override.disable);self.addCleanup(self.unlock)
        self.rt=D.runtime();self.now=time.time();self.clock=lambda:self.now-5000
        self.make_cup('cup',self.now-3000,self.now-1000)
        self.register('cup', [('a','ta'),('b','tb')])
        for uid,team in [('roster-a','ta'),('roster-b','tb')]:
            actor=G.actor_for(self.rt.registration,uid)
            sub=R.submit(self.rt.flow.registry,actor,team,'cup','bot.py',BOT,idempotency_key='one',deadline_at=self.now-1000,now=self.clock)
            claim=R.claim_check(self.rt.flow.registry,sub['id'])
            R.record_verdict(self.rt.flow.registry,claim,verdict(BOT))
        catalogue={'one':'a'*64,'two':'b'*64,'three':'c'*64,'four':'d'*64}
        M.create_pool(self.rt.flow.store,'pool',catalogue,'1.2.6',play=['one'],tiebreak_normal=['two'],tiebreak_final=['two','three','four'])
        F.open_bracket(self.rt.flow,'cup','cup',['ta','tb'],'pool',catalogue,'1.2.6',deadline_at=self.now-1000)
        F.start_round(self.rt.flow,'cup',1,'organizer')
        B.run_round(self.rt.flow.store,'cup',1,lower_wins)
        self.sid=next(iter(self.rt.flow.store.snapshot()['series']))
        self.client=APIClient();self.client.force_authenticate(self.a)
    def unlock(self):
        for p in (self.root/'submissions').glob('*'):
            if p.is_dir():p.chmod(0o700)
    def make_cup(self,tid,registration,submission):
        T.create(self.rt.tournaments,ADM,tid,'Tournament '+tid,'',registration,submission,idempotency_key=tid,now=self.clock)
        T.approve(self.rt.tournaments,ADM,tid,confirm=True,now=self.clock)
        T.open_registration(self.rt.tournaments,ADM,tid,now=self.clock)
    def register(self,tid,entries):
        rows=[{'email':u+'@uni.edu','team_key':t,'team_name':t.upper(),'member_number':1,'role':'captain'} for u,t in entries]
        G.import_roster(self.rt.registration,ADM,tid,rows,now=self.clock)
        roster=G.list_roster(self.rt.registration,ADM,tid)
        issued=G.issue_codes(self.rt.registration,ADM,tid,now=self.clock)['issued']
        codes={c['entry_id']:c['code'] for c in issued}
        for entry in roster:
            name=entry['email'].split('@')[0];uid='roster-'+name
            G.claim(self.rt.registration,tid,entry['email'],codes[entry['id']],uid,now=self.clock)
            G.confirm_email(self.rt.registration,tid,uid,now=self.clock)
    def url(self,suffix):return '/api/v1/tournaments/cup/'+suffix
    def post(self,path,data,key='request-one'):
        return self.client.post(path,data,format='json',HTTP_IDEMPOTENCY_KEY=key)
    def open(self):
        result=self.post(self.url('disputes/'),{'series_id':self.sid,'title':'Review match','description':'Please review the recorded event.'})
        self.assertEqual(result.status_code,201,result.data);return result.data
    def test_anonymous_cannot_read_any_protected_feature(self):
        self.client.force_authenticate(None)
        for path in ('analytics/','analytics.csv','live/','disputes/','dispute-notices/','teams/ta/submissions/'):
            response=self.client.get(self.url(path));self.assertEqual(response.status_code,401,path)
    def test_foreign_scope_and_missing_tournament_have_same_404(self):
        self.client.force_authenticate(self.outsider)
        for tid in ('cup','missing'):
            for feature in ('analytics/','live/','disputes/','dispute-notices/'):
                self.assertEqual(self.client.get(f'/api/v1/tournaments/{tid}/{feature}').status_code,404)
    def test_participant_actor_comes_from_current_verified_roster(self):
        self.assertIn('cup',D.actor(self.a).tournament_ids)
        identity=Identity.objects.get(user=self.a);identity.roster_user_id='unregistered';identity.save()
        self.assertEqual(self.client.get(self.url('analytics/')).status_code,404)
    def test_organizer_assignment_revocation_applies_to_next_poll(self):
        self.client.force_authenticate(self.org)
        self.assertEqual(self.client.get(self.url('live/')).status_code,200)
        OrganizerAssignment.objects.filter(user=self.org).update(active=False)
        self.assertEqual(self.client.get(self.url('live/')).status_code,404)
    def test_analytics_use_official_results_and_exclude_source_and_host_paths(self):
        before=self.rt.flow.store.snapshot()
        response=self.client.get(self.url('analytics/'));self.assertEqual(response.status_code,200,response.data)
        data=response.data;self.assertEqual(data['totals']['completed'],1);self.assertEqual(data['totals']['teams'],2)
        self.assertEqual(sum(t['wins'] for t in data['teams']),1)
        self.assertEqual(len(data['versions']),2);self.assertEqual(sum(v['wins'] for v in data['versions']),1);self.assertNotIn('source',json.dumps(data));self.assertNotIn(str(self.root),json.dumps(data))
        self.assertEqual(before,self.rt.flow.store.snapshot())
        export=self.client.get(self.url('analytics.csv'));self.assertEqual(export.status_code,200)
        self.assertIn('private',export['Cache-Control']);self.assertIn(b'team,played,wins',export.content)
    def test_live_board_is_allowlisted_and_archived_tournament_returns_gone(self):
        game=next(iter(self.rt.flow.store.snapshot()['matches']))
        path=self.root/'live'/f'{game}.json';path.parent.mkdir()
        path.write_text(json.dumps({'width':20,'height':20,'round':9,'updated_at':time.time(),'finished':False,
           'robots':[{'id':1,'x':1,'y':2,'team':1,'kind':1,'health':9,'cheese':0,'dir':1,'source':'SECRET'}],
           'walls':[],'dirt':[],'indicator':'PRIVATE'}))
        response=self.client.get(self.url('live/'));self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['items'][0]['board']['round'],9)
        self.assertNotIn('PRIVATE',json.dumps(response.data));self.assertNotIn('SECRET',json.dumps(response.data))
        with self.rt.tournaments.store.transaction() as state:state['tournaments']['cup']['status']='archived'
        for user in (self.a,self.org,self.admin):
            self.client.force_authenticate(user);self.assertEqual(self.client.get(self.url('live/')).status_code,410)
    def test_source_download_is_team_private_and_staff_read_is_audited(self):
        own = self.client.get(self.url('submissions/ta-v1/download/'))
        self.assertEqual(own.status_code, 200)
        self.assertTrue(own.streaming)
        self.assertEqual(own['Content-Type'], 'text/x-python')
        self.assertEqual(own['Content-Disposition'], 'attachment; filename="bot.py"')
        self.assertEqual(own['Content-Length'], str(len(BOT)))
        self.assertEqual(own['Cache-Control'], 'private, no-store')
        self.assertEqual(b''.join(own.streaming_content), BOT)
        other=self.client.get(self.url('submissions/tb-v1/download/'));self.assertEqual(other.status_code,404)
        self.assertFalse(other.streaming)
        self.client.force_authenticate(self.org)
        staff = self.client.get(self.url('submissions/tb-v1/download/'))
        self.assertEqual(staff.status_code, 200)
        self.assertEqual(b''.join(staff.streaming_content), BOT)
        self.assertTrue(any(a['action']=='download' for a in self.rt.flow.registry.store.snapshot()['audit']))
    def test_upload_uses_official_deadline_and_staff_cannot_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        response=self.client.post(self.url('teams/ta/submissions/'),{'file':SimpleUploadedFile('bot.py',BOT)},format='multipart',HTTP_IDEMPOTENCY_KEY='late')
        self.assertEqual(response.status_code,409)
        self.client.force_authenticate(self.org)
        response=self.client.post(self.url('teams/ta/submissions/'),{'file':SimpleUploadedFile('bot.py',BOT)},format='multipart',HTTP_IDEMPOTENCY_KEY='staff')
        self.assertEqual(response.status_code,403)
        self.assertEqual(len(self.rt.flow.registry.store.snapshot()['submissions']),2)
    def test_bundle_upload_queues_a_check_and_exports_only_to_its_team(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from backend.submission_bundle.tests.test_bundle import archive, FILES
        self.make_cup('uploads',self.now+3000,self.now+5000)
        self.register('uploads',[('a','upload-a')])
        path='/api/v1/tournaments/uploads/teams/upload-a/submissions/'
        response=self.client.post(path,{'file':SimpleUploadedFile('strategy.zip',archive(FILES))},format='multipart',HTTP_IDEMPOTENCY_KEY='bundle-upload')
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(response.data['format'],'python-bundle')
        from backend.work_queue import jobs as J
        self.assertTrue(any(j['payload'].get('submission_id')==response.data['id'] for j in J.list_jobs(self.rt.flow.queue)))
        download=self.client.get('/api/v1/tournaments/uploads/submissions/'+response.data['id']+'/download/')
        self.assertEqual(download.status_code,200)
        self.assertEqual(download['Content-Type'],'application/zip')
        self.assertTrue(download.streaming)
        self.assertEqual(download['Content-Disposition'], 'attachment; filename="bot-bundle.zip"')
        self.assertEqual(download['Cache-Control'], 'private, no-store')
        data = b''.join(download.streaming_content)
        self.assertEqual(download['Content-Length'], str(len(data)))
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            self.assertEqual(bundle.read('bot.py'), FILES['bot.py'])
            self.assertEqual(bundle.read('strategy.py'), FILES['strategy.py'])
            self.assertEqual(json.loads(bundle.read('requirements.json')), json.loads(FILES['requirements.json']))
        self.client.force_authenticate(self.b)
        self.assertEqual(self.client.get('/api/v1/tournaments/uploads/submissions/'+response.data['id']+'/download/').status_code,404)

    def make_upload_target(self, *, deadline_offset=5000):
        self.make_cup('uploads', self.now - 3000, self.now + deadline_offset)
        self.register('uploads', [('a', 'upload-a')])
        return '/api/v1/tournaments/uploads/teams/upload-a/submissions/'

    def upload_file(self, path, *, name='bot.py', raw=BOT, key='upload'):
        return self.client.post(path, {'file': SimpleUploadedFile(name, raw)}, format='multipart',
                                HTTP_IDEMPOTENCY_KEY=key)

    def assert_upload_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.data)
        error = response.data['error']
        self.assertEqual(error['code'], code)
        self.assertEqual(error['request_id'], response['X-Request-ID'])
        return error

    def test_upload_requires_multipart_and_one_file(self):
        path = self.make_upload_target()
        self.assert_upload_error(self.post(path, {'file': 'bot.py'}), 415, 'UNSUPPORTED_MEDIA_TYPE')
        bodies = ({'file': 'bot.py'}, {'file': [SimpleUploadedFile('bot.py', BOT),
                                               SimpleUploadedFile('bot.py', BOT)]},
                  {'file': SimpleUploadedFile('bot.py', BOT), 'deadline': self.now + 9000})
        for body in bodies:
            response = self.client.post(path, body, format='multipart', HTTP_IDEMPOTENCY_KEY='one')
            self.assert_upload_error(response, 400, 'VALIDATION_ERROR')
        self.assert_upload_error(self.upload_file(path, key=''), 400, 'VALIDATION_ERROR')
        self.assert_upload_error(self.upload_file(path, name='strategy.py'), 422, 'BOT_VALIDATION_FAILED')
        self.assertEqual(self.client.get(path).data['items'], [])

    def test_upload_reports_raw_and_expanded_size_limits(self):
        from backend.submission_bundle import bundle as BU
        from backend.submission_bundle.tests.test_bundle import archive
        path = self.make_upload_target()
        for name, data in (
            ('bot.py', b'x' * (BU.MAX_BYTES + 1)),
            ('strategy.zip', archive({'bot.py': BOT, 'helper.py': b'#' * BU.MAX_BYTES})),
            ('strategy.zip', archive({'bot.py': BOT, **{f'helper{i}.py': b'' for i in range(BU.MAX_FILES)}})),
        ):
            with self.subTest(name=name, size=len(data)):
                self.assert_upload_error(self.upload_file(path, name=name, raw=data), 413, 'FILE_TOO_LARGE')
        self.assert_upload_error(self.upload_file(path, name='strategy.zip', raw=b'not a ZIP'), 422,
                                 'BOT_VALIDATION_FAILED')
        self.assertEqual(self.client.get(path).data['items'], [])

    def test_static_refusal_has_findings_stays_in_history_and_never_queues(self):
        path = self.make_upload_target()
        created = self.upload_file(path)
        self.assertEqual(created.status_code, 201, created.data)
        sid = created.data['id']
        claim = R.claim_check(self.rt.flow.registry, sid)
        R.record_verdict(self.rt.flow.registry, claim, verdict(BOT))
        for _ in range(2):
            result = self.upload_file(path, key='invalid', raw=b'def turn(\n')
            error = self.assert_upload_error(result, 422, 'BOT_VALIDATION_FAILED')
            self.assertEqual(error['details']['submission_id'], 'upload-a-v2')
            finding = error['details']['reasons'][0]
            self.assertEqual(finding['line'], 1)
            self.assertEqual(error['message'], finding['message'])
        history = self.client.get(path).data['items']
        self.assertEqual([(item['id'], item['is_active']) for item in history],
                         [(sid, True), ('upload-a-v2', False)])
        self.assertEqual([job['payload']['submission_id'] for job in J.list_jobs(self.rt.flow.queue)
                          if job['kind'] == J.CHECK_SUBMISSION].count('upload-a-v2'), 0)

    def test_upload_observes_extension_and_reuses_version_and_job_on_retry(self):
        path = self.make_upload_target(deadline_offset=-1000)
        self.assert_upload_error(self.upload_file(path), 409, 'STATE_CONFLICT')
        T.extend_deadline(self.rt.tournaments, ADM, 'uploads', T.SUBMISSION, self.now + 4000,
                          'Approved fixture extension', confirm=True)
        first = self.upload_file(path)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(self.upload_file(path).data, first.data)
        self.assert_upload_error(self.upload_file(path, raw=BOT + b'\n'), 409, 'STATE_CONFLICT')
        jobs = [job for job in J.list_jobs(self.rt.flow.queue)
                if job['payload'].get('submission_id') == first.data['id']]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['status'], J.QUEUED)
        self.assertNotIn('check_job', first.data)

    def test_captain_in_both_tournaments_cannot_submit_a_team_under_wrong_tournament(self):
        self.make_upload_target()
        path = '/api/v1/tournaments/uploads/teams/ta/submissions/'
        self.assert_upload_error(self.upload_file(path, key='one'), 404, 'NOT_FOUND')
        self.assert_upload_error(self.upload_file(path, key='new'), 404, 'NOT_FOUND')
        self.assertEqual(len(self.rt.flow.registry.store.snapshot()['submissions']), 2)

    def test_successful_logins_do_not_use_the_shared_failure_budget(self):
        for user in (self.a, self.b) * 6:
            browser = Client(enforce_csrf_checks=True)
            csrf = browser.get('/api/v1/auth/session/').json()['csrf']
            response = browser.post('/api/v1/auth/login/', {
                'username': user.username, 'password': 'test-fixture-passphrase',
            }, content_type='application/json', HTTP_X_CSRFTOKEN=csrf)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(browser.get('/api/v1/auth/session/').json()['user']['id'], user.pk)
        self.assertFalse(LoginAttempt.objects.exists())

    def test_login_rate_limit_is_durable_and_failure_does_not_create_a_session(self):
        client=Client(enforce_csrf_checks=True)
        csrf=client.get('/api/v1/auth/session/').json()['csrf']
        for _ in range(10):
            result=client.post('/api/v1/auth/login/',data=json.dumps({'username':'missing-account','password':'wrong-fixture'}),content_type='application/json',HTTP_X_CSRFTOKEN=csrf)
            self.assertEqual(result.status_code,401)
        result=client.post('/api/v1/auth/login/',data=json.dumps({'username':'missing-account','password':'wrong-fixture'}),content_type='application/json',HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(result.status_code,429)
        other_source=client.post('/api/v1/auth/login/',data=json.dumps({'username':'missing-account','password':'wrong-fixture'}),content_type='application/json',HTTP_X_CSRFTOKEN=csrf,REMOTE_ADDR='127.0.0.2')
        self.assertEqual(other_source.status_code,429)
        other_account=client.post('/api/v1/auth/login/',data=json.dumps({'username':'another-account','password':'wrong-fixture'}),content_type='application/json',HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(other_account.status_code,429)
        self.assertIsNone(client.get('/api/v1/auth/session/').json()['user'])

    def test_dispute_idempotency_own_team_visibility_and_no_result_changes(self):
        before=self.rt.flow.store.snapshot();item=self.open()
        again=self.post(self.url('disputes/'),{'series_id':self.sid,'title':'Review match','description':'Please review the recorded event.'})
        self.assertEqual(again.data,item);self.assertEqual(Dispute.objects.count(),1);self.assertEqual(AuditEvent.objects.count(),1)
        self.client.force_authenticate(self.b)
        self.assertEqual(self.client.get(self.url(f"disputes/{item['id']}/")).status_code,404)
        self.assertEqual(self.client.get(self.url('disputes/')).data['items'],[])
        self.assertEqual(before,self.rt.flow.store.snapshot())
    def test_comments_status_transitions_versions_and_closed_records(self):
        item=self.open();path=self.url(f"disputes/{item['id']}/")
        self.assertEqual(self.post(path,{'expected_version':1,'status':'resolved','resolution':'win'},'bad').status_code,403)
        comment=self.post(path,{'expected_version':1,'message':'Extra detail'},'comment');self.assertEqual(comment.data['version'],2)
        self.assertEqual(self.post(path,{'expected_version':1,'message':'stale'},'stale').status_code,409)
        self.client.force_authenticate(self.org)
        self.assertEqual(self.post(path,{'expected_version':2,'status':[],'resolution':'bad fixture'},'invalid-status').status_code,400)
        reviewed=self.post(path,{'expected_version':2,'status':'reviewing','resolution':'Reviewing recorded evidence.'},'review')
        self.assertEqual(reviewed.data['status'],'reviewing')
        resolved=self.post(path,{'expected_version':3,'status':'resolved','resolution':'Recorded outcome stands.'},'resolve')
        self.assertEqual(resolved.data['version'],4)
        self.assertEqual(self.post(path,{'expected_version':4,'message':'closed'},'closed').status_code,409)
        self.assertEqual(AuditEvent.objects.count(),4)

    def test_dispute_notices_use_committed_events_and_current_scope(self):
        item = self.open()
        notices = self.url('dispute-notices/')
        detail = self.url(f"disputes/{item['id']}/")
        self.assertEqual(self.client.get(notices).data['items'], [])
        self.assertEqual(self.post(detail, {'expected_version': 1, 'message': 'Private comment'}, 'comment').status_code, 200)

        for staff in (self.admin, self.org):
            self.client.force_authenticate(staff)
            response = self.client.get(notices)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            opening, = response.data['items']
            self.assertEqual(set(opening), {'id', 'kind', 'title', 'created_at'})
            self.assertEqual((opening['kind'], opening['title']), ('opened', 'Review match'))
        self.assertEqual(self.post(detail, {'expected_version': 1, 'status': 'reviewing', 'resolution': 'Stale'}, 'stale').status_code, 409)
        for version, status in enumerate(('reviewing', 'awaiting_participant', 'reviewing', 'resolved'), 2):
            body = {'expected_version': version, 'status': status, 'resolution': 'Private reason'}
            accepted = self.post(detail, body, f'review-{version}')
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(self.post(detail, body, f'review-{version}').data, accepted.data)
        self.assertEqual(self.client.get(notices).data['items'], [opening])
        OrganizerAssignment.objects.filter(user=self.org).update(active=False)
        self.assertEqual(self.client.get(notices).status_code, 404)

        self.client.force_authenticate(self.b)
        self.assertEqual(self.client.get(notices).data['items'], [])
        self.client.force_authenticate(self.a)
        reviews = self.client.get(notices).data['items']
        self.assertEqual(len(reviews), 3)
        event_ids = list(Dispute.objects.get(pk=item['id']).events.filter(kind='status_changed')
                         .order_by('-pk').values_list('pk', flat=True))
        self.assertEqual(len(event_ids), 4)
        self.assertEqual([review['id'] for review in reviews], event_ids[:3])
        for review in reviews:
            self.assertEqual(set(review), set(opening))
            self.assertEqual((review['kind'], review['title']), ('status_changed', 'Review match'))
        Identity.objects.filter(user=self.a).update(roster_user_id='unregistered')
        self.assertEqual(self.client.get(notices).status_code, 404)

    def test_idempotency_payload_mismatch_and_revoked_membership_cannot_replay(self):
        self.open()
        mismatch=self.post(self.url('disputes/'),{'series_id':self.sid,'title':'Changed','description':'different'})
        self.assertEqual(mismatch.status_code,409)
        Identity.objects.filter(user=self.a).update(roster_user_id='no-scope')
        self.assertEqual(self.post(self.url('disputes/'),{'series_id':self.sid,'title':'Review match','description':'Please review the recorded event.'}).status_code,404)
    def test_history_is_append_only_in_postgresql(self):
        self.open();audit=AuditEvent.objects.first()
        with self.assertRaises(DatabaseError),transaction.atomic():AuditEvent.objects.filter(pk=audit.pk).update(action='tampered')
        with self.assertRaises(DatabaseError),transaction.atomic():AuditEvent.objects.filter(pk=audit.pk).delete()
        self.assertEqual(AuditEvent.objects.get(pk=audit.pk).action,'dispute_opened')
    def test_audit_failure_rolls_back_dispute_and_receipt(self):
        from unittest.mock import patch
        with patch.object(AuditEvent.objects,'create',side_effect=DatabaseError('fixture failure')):
            with self.assertRaises(DatabaseError):self.open()
        self.assertEqual(Dispute.objects.count(),0);self.assertEqual(Receipt.objects.count(),0)
        self.client.force_authenticate(self.org)
        self.assertEqual(self.client.get(self.url('dispute-notices/')).data['items'], [])
    def test_operations_are_admin_only_and_omit_raw_details(self):
        self.assertEqual(self.client.get('/api/v1/admin/operations/').status_code,403)
        self.client.force_authenticate(self.admin)
        response=self.client.get('/api/v1/admin/operations/');self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['status']['open_incidents'],0)
    def test_provisioned_organizer_assignment_and_revocation_are_audited(self):
        from django.core.management import call_command
        call_command('provision_access','outsider',organizer_tournament='cup',reason='Fixture assignment',stdout=io.StringIO())
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.url('live/')).status_code,200)
        call_command('provision_access','outsider',organizer_tournament='cup',revoke=True,reason='Fixture revoked',stdout=io.StringIO())
        self.assertEqual(self.client.get(self.url('live/')).status_code,404)
        self.assertEqual(list(AuditEvent.objects.values_list('action',flat=True)),['organizer_assigned','organizer_revoked'])

    def test_participant_provisioning_rejects_a_different_official_email(self):
        from django.core.management import call_command, CommandError
        with self.assertRaises(CommandError):
            call_command('provision_access','outsider',roster_user_id='roster-a',reason='Fixture mismatch',stdout=io.StringIO())
        self.assertFalse(Identity.objects.filter(user=self.outsider).exists())

    def test_mutation_rechecks_account_activation_inside_the_transaction(self):
        get_user_model().objects.filter(pk=self.a.pk).update(is_active=False)
        response=self.post(self.url('disputes/'),{'series_id':self.sid,'title':'Blocked','description':'No scope.'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(Dispute.objects.count(),0)

    def test_real_session_login_enforces_csrf_and_rejects_bad_credentials_uniformly(self):
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/v1/auth/login/',data=json.dumps({'username':'captain-a','password':'test-fixture-passphrase'}),content_type='application/json').status_code,403)
        token=client.get('/api/v1/auth/session/').json()['csrf']
        result=client.post('/api/v1/auth/login/',data=json.dumps({'username':'captain-a','password':'test-fixture-passphrase'}),content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(result.status_code,200);self.assertEqual(client.get(self.url('analytics/')).status_code,200)
        self.assertEqual(client.post('/api/v1/auth/logout/').status_code,403)
        self.assertEqual(client.post('/api/v1/auth/logout/',HTTP_X_CSRFTOKEN=result.json()['csrf']).status_code,200)
        self.assertEqual(client.get(self.url('analytics/')).status_code,401)

    def test_login_failures_and_session_csrf_share_the_error_contract(self):
        client=Client(enforce_csrf_checks=True)
        token=client.get('/api/v1/auth/session/').json()['csrf']
        bad_login=client.post('/api/v1/auth/login/',data=json.dumps({'username':'captain-a','password':'wrong-fixture'}),content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(bad_login.status_code,401)
        self.assertEqual(bad_login.json()['error']['code'],'UNAUTHENTICATED')
        self.assertEqual(bad_login.json()['error']['request_id'],bad_login['X-Request-ID'])
        logged_in=client.post('/api/v1/auth/login/',data=json.dumps({'username':'captain-a','password':'test-fixture-passphrase'}),content_type='application/json',HTTP_X_CSRFTOKEN=token)
        self.assertEqual(logged_in.status_code,200)
        csrf_failure=client.post('/api/v1/auth/logout/')
        self.assertEqual(csrf_failure.status_code,403)
        self.assertEqual(csrf_failure.json()['error']['code'],'FORBIDDEN')
        self.assertIn('CSRF verification failed',csrf_failure.json()['error']['message'])
        self.assertEqual(csrf_failure.json()['error']['details'],{})
        self.assertEqual(csrf_failure.json()['error']['request_id'],csrf_failure['X-Request-ID'])

    def test_conflict_receipt_replay_gets_a_fresh_request_id(self):
        item=self.open()
        path=self.url(f"disputes/{item['id']}/")
        first=self.post(path,{'expected_version':0,'message':'stale fixture'},'stale-fixture')
        second=self.post(path,{'expected_version':0,'message':'stale fixture'},'stale-fixture')
        for response in (first,second):
            self.assertEqual(response.status_code,409)
            self.assertEqual(response.json()['error']['code'],'STATE_CONFLICT')
            self.assertEqual(response.json()['error']['request_id'],response['X-Request-ID'])
        self.assertNotEqual(first['X-Request-ID'],second['X-Request-ID'])
        stored=Receipt.objects.get(key='stale-fixture').body
        self.assertNotIn('request_id',stored['error'])
        self.assertEqual(Dispute.objects.get(pk=item['id']).version,1)

    def test_hidden_and_missing_tournaments_have_identical_error_bodies(self):
        self.client.force_authenticate(self.outsider)
        errors=[]
        for tid in ('cup','missing'):
            response=self.client.get(f'/api/v1/tournaments/{tid}/analytics/')
            self.assertEqual(response.status_code,404)
            error=response.json()['error']
            self.assertEqual(error.pop('request_id'),response['X-Request-ID'])
            errors.append(error)
        self.assertEqual(errors[0],errors[1])
        self.assertEqual(errors[0]['code'],'NOT_FOUND')
