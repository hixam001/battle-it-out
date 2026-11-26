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
    from backend.webapp.tests import FeatureAPI

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
