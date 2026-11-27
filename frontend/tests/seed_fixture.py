"""Seed the browser suite against a fresh local database and empty state directory."""
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
    from backend.notifications import notifications
    from backend.registration import registration
    from backend.submission_registry import registry
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
