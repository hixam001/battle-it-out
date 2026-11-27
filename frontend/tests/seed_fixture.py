"""Seed the browser suite against a fresh local database and empty state directory."""
import gzip
import os
import shutil
from pathlib import Path

import django


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.webapp.settings')
    django.setup()

    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.db import transaction
    from backend.match_orchestrator import bracket, maps, orchestrator, replays
    from backend.match_orchestrator.tests.test_bracket import MAPS, teams
    from backend.match_orchestrator.tests.test_maps import ENGINE, FILES, GOOD, make_jar
    from backend.match_orchestrator.tests.test_tiebreak import COIN, Coin, won
    from backend.match_runner import match_log
    from backend.notifications import notifications
    from backend.registration import registration
    from backend.submission_registry import registry
    from backend.tournaments import tournaments
    from backend.webapp.models import OrganizerAssignment
    from backend.webapp.tests import ADM, BOT, FeatureAPI, verdict
    from backend.work_queue import jobs

    connection = settings.DATABASES['default']
    host = connection['HOST']
    state = Path(os.environ['BIO_DATA_DIR'])
    if (not settings.DEBUG or not connection['NAME'].startswith('bio_qa_')
            or not (host in ('127.0.0.1', 'localhost', '::1') or host.startswith('/tmp/'))
            or not state.is_absolute() or state.exists()):
        raise SystemExit('Use local debug mode, a new bio_qa_* database and a new absolute BIO_DATA_DIR.')

    with transaction.atomic():
        if get_user_model().objects.exists():
            raise SystemExit('Migrate a fresh disposable database before seeding the fixture.')
        FeatureAPI.setUpTestData()
        fixture = FeatureAPI()
        try:
            fixture.setUp()
            with fixture.rt.tournaments.store.transaction() as data:
                cup = data['tournaments']['cup']
                cup['name'] = 'QA FIXTURE — not a real competition'
                cup['description'] = 'Local interface test fixture.'
            fixture.make_cup('upload-fixture', fixture.now + 3600, fixture.now + 7200)
            registration.import_roster(fixture.rt.registration, ADM, 'upload-fixture', [
                {'email': 'a@uni.edu', 'team_key': 'upload-team', 'team_name': 'Fixture Upload Team',
                 'member_number': 1, 'role': 'captain'},
                {'email': 'b@uni.edu', 'team_key': 'upload-team', 'team_name': 'Fixture Upload Team',
                 'member_number': 2, 'role': 'member'},
            ])
            roster = registration.list_roster(fixture.rt.registration, ADM, 'upload-fixture')
            issued = registration.issue_codes(fixture.rt.registration, ADM, 'upload-fixture')['issued']
            codes = {item['entry_id']: item['code'] for item in issued}
            for entry in roster:
                user = 'roster-' + entry['email'].split('@')[0]
                registration.claim(fixture.rt.registration, 'upload-fixture', entry['email'], codes[entry['id']], user)
                registration.confirm_email(fixture.rt.registration, 'upload-fixture', user)
            stored = fixture.rt.flow.registry
            actor = registration.actor_for(fixture.rt.registration, 'roster-a')
            source = registry.submit(stored, actor, 'upload-team', 'upload-fixture', 'bot.py', BOT,
                                     idempotency_key='fixture-source', deadline_at=fixture.now + 7200)
            registry.record_verdict(stored, registry.claim_check(stored, source['id']), verdict(BOT))
            fixture.make_cup('tied-fixture', fixture.now - 3000, fixture.now - 1000)
            store = fixture.rt.flow.store
            official = store.snapshot()
            log_mid = official['series'][fixture.sid]['games'][0]['match_id']
            game = official['matches'][log_mid]
            attempt = game['attempts'][0]
            log_context = {
                'trace_id': attempt['trace_id'], 'match_id': log_mid, 'attempt': 1,
                'teams': {'A': game['team_a'], 'B': game['team_b']},
                'submissions': {'A': game['submission_a'], 'B': game['submission_b']},
                'engine_version': ENGINE, 'map': game['map'], 'started_at': attempt['started_at'],
                'finished_at': attempt['finished_at'],
            }
            winner = game['result']['winner_side']
            log_result = {'outcome': 'completed', 'classification': 'normal', 'kind': 'score', 'winner': winner,
                          'reason': 'Won on points', 'round': 1}
            events = match_log.build_events(log_result, log_context,
                                            '[A: #5@1] First side output\n[B: #6@1] Second side output\n')
            relative_log = Path('out', 'matches', log_mid, 'attempt-1', 'match-20261128-000001.events.jsonl')
            fixture_log = fixture.root / relative_log
            fixture_log.parent.mkdir(parents=True, exist_ok=True)
            log_info = match_log.write_jsonl(fixture_log, events)
            log_info['path'] = str(state / relative_log)
            with store.transaction() as data:
                data['matches'][log_mid]['attempts'][0]['summary']['structured_log'] = log_info
            orchestrator.create_match(store, 'paused-fixture-match', 'ta', 'tb', 'one', 'ta-v1', 'tb-v1', max_attempts=1)
            orchestrator.queue_match(store, 'paused-fixture-match')
            _, attempt = orchestrator.claim(store, 'paused-fixture-match', 'fixture-worker')
            orchestrator.finish(store, 'paused-fixture-match', attempt.attempt, 'fixture-worker',
                                {'outcome': 'platform_failure', 'kind': 'fixture_error'})
            queue = fixture.rt.flow.queue
            jobs.enqueue(queue, jobs.RUN_ROUND, {'bracket_id': 'operations-fixture', 'round_no': 1})
            jobs.fail(queue, jobs.claim_next(queue, 'fixture-worker'), 'Fixture dead job', permanent=True)
            bracket.create_bracket(store, 'tied-fixture', teams(2), MAPS)
            with store.transaction() as data:
                data['brackets']['tied-fixture']['tournament_id'] = 'tied-fixture'
            bracket.start_round(store, 'tied-fixture', 1, 'fixture-organizer')
            bracket.run_round(store, 'tied-fixture', 1, lambda _: won('A', reason=COIN), coin=Coin('B'))
            with fixture.rt.tournaments.store.transaction() as data:
                data['tournaments']['tied-fixture']['status'] = tournaments.COMPLETED
            pairing = store.snapshot()['brackets']['tied-fixture']['rounds'][0]['matches'][0]
            series = store.snapshot()['series'][pairing['series_id']]
            match_id = series['games'][-1]['match_id']
            replay_source = fixture.root / 'browser-fixture.bc26'
            replay_source.write_bytes(gzip.compress(b'Local browser download fixture.' * 40))
            replays.register_replay(fixture.rt.vault, 'tied-fixture', match_id, replay_source, None)
            replay_source.unlink()
            organizer = registry.Actor(str(FeatureAPI.org.pk), 'organizer')
            fixture.make_cup('organizer-archive', fixture.now - 3000, fixture.now - 1000)
            with fixture.rt.tournaments.store.transaction() as data:
                data['tournaments']['organizer-archive']['status'] = tournaments.COMPLETED
            OrganizerAssignment.objects.create(user=FeatureAPI.org, tournament_id='organizer-archive')
            OrganizerAssignment.objects.create(user=FeatureAPI.org, tournament_id='organizer-draft')
            tournaments.create(fixture.rt.tournaments, organizer, 'organizer-draft', 'Unsubmitted Organizer fixture',
                               '', fixture.now + 7200, fixture.now + 10800, idempotency_key='organizer-draft')
            for suffix in ('approve', 'reject', 'changed'):
                tid = f'approval-{suffix}'
                OrganizerAssignment.objects.create(user=FeatureAPI.org, tournament_id=tid)
                tournaments.create(fixture.rt.tournaments, organizer, tid, f'Fixture to {suffix}',
                                   'An Organizer-created fixture for the approval queue.',
                                   fixture.now + 7200, fixture.now + 10800, idempotency_key=tid)
                tournaments.submit_for_approval(fixture.rt.tournaments, organizer, tid)
            tournaments.create(fixture.rt.tournaments, ADM, 'retired-fixture', 'Retired fixture', '',
                               fixture.now + 7200, fixture.now + 10800, idempotency_key='retired-fixture')
            tournaments.delete(fixture.rt.tournaments, ADM, 'retired-fixture',
                               'Private approval-suite deletion reason', confirm=True)
            fixture.make_cup('deadline-fixture', fixture.now - 3600, fixture.now - 1800)
            fixture.register('deadline-fixture', [('a', 'deadline-a'), ('b', 'deadline-b')])
            fixture.make_cup('invite-fixture', fixture.now + 3600, fixture.now + 7200)
            registration.import_roster(fixture.rt.registration, ADM, 'invite-fixture', [
                {'email': 'unclaimed@uni.edu', 'team_key': 'invite-team', 'team_name': 'Invitation Fixture',
                 'member_number': 1, 'role': 'captain'},
            ])
            registration.issue_codes(fixture.rt.registration, ADM, 'invite-fixture')
            fixture.make_cup('issue-fixture', fixture.now + 3600, fixture.now + 7200)
            OrganizerAssignment.objects.create(user=FeatureAPI.org, tournament_id='issue-fixture')
            registration.import_roster(fixture.rt.registration, ADM, 'issue-fixture', [
                {'email': f'{name}@uni.edu', 'team_key': f'issue-{name}', 'team_name': name,
                 'member_number': 1, 'role': 'captain'}
                for name in ('first-ready', 'second-ready', 'already-issued')
            ])
            issued_entry = next(entry for entry in registration.list_roster(fixture.rt.registration, ADM, 'issue-fixture')
                                if entry['email'] == 'already-issued@uni.edu')
            registration.issue_codes(fixture.rt.registration, ADM, 'issue-fixture', [issued_entry['id']])
            fixture.make_cup('roster-fixture', fixture.now + 3600, fixture.now + 7200)
            fixture.register('roster-fixture', [('a', 'registered-roster-team')])
            OrganizerAssignment.objects.create(user=FeatureAPI.org, tournament_id='roster-fixture')
            jar = make_jar(fixture.root / 'fixture-engine.jar', FILES)
            maps.create_pool(store, 'browser-map-pool', maps.load_engine_maps(jar), ENGINE, **GOOD)
            fixture.make_cup('round-fixture', fixture.now - 3600, fixture.now - 1800)
            fixture.register('round-fixture', [('a', 'round-a'), ('b', 'round-b')])
            OrganizerAssignment.objects.create(user=FeatureAPI.org, tournament_id='round-fixture')
            tournaments.edit(fixture.rt.tournaments, ADM, 'round-fixture', {'map_pool_id': 'browser-map-pool'},
                             now=fixture.clock)
            for team, person in (('round-a', 'roster-a'), ('round-b', 'roster-b')):
                actor = registration.actor_for(fixture.rt.registration, person)
                submission = registry.submit(stored, actor, team, 'round-fixture', 'bot.py', BOT,
                                             idempotency_key=f'fixture-{team}', deadline_at=fixture.now - 1800,
                                             now=fixture.clock)
                registry.record_verdict(stored, registry.claim_check(stored, submission['id']), verdict(BOT))
            for i in range(1, 24):
                cup = 'cup' if i <= 22 else 'historical'
                title = f'Fixture notice {i:02d}' if i <= 22 else 'Historical fixture notice'
                notifications.notify(fixture.rt.notifications, 'announcement', cup, ['roster-a'],
                                     {'headline': title, 'message': 'Test dashboard notification.'},
                                     event_key=f'fixture-{i}', now=lambda: fixture.now - 24 + i)
            shutil.copytree(fixture.root, state)
        finally:
            fixture.doCleanups()
    print('Seeded local browser QA accounts, tournament and notices.')


if __name__ == '__main__':
    main()
