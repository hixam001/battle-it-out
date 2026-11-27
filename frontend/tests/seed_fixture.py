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
    from backend.match_orchestrator import bracket, replays
    from backend.match_orchestrator.tests.test_bracket import MAPS, teams
    from backend.match_orchestrator.tests.test_tiebreak import COIN, Coin, won
    from backend.notifications import notifications
    from backend.registration import registration
    from backend.submission_registry import registry
    from backend.tournaments import tournaments
    from backend.webapp.models import OrganizerAssignment
    from backend.webapp.tests import ADM, BOT, FeatureAPI, verdict

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
