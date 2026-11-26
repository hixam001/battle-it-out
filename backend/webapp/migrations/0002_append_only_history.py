# SPDX-License-Identifier: AGPL-3.0-only
from django.db import migrations

def protect(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        raise RuntimeError('The feature platform requires PostgreSQL')
    schema_editor.execute('''CREATE FUNCTION bio_reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Battle It Out history is append-only'; END; $$''')
    for table in ('webapp_auditevent', 'webapp_disputeevent'):
        schema_editor.execute(f'CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION bio_reject_history_change()')

def unprotect(apps, schema_editor):
    for table in ('webapp_auditevent', 'webapp_disputeevent'):
        schema_editor.execute(f'DROP TRIGGER immutable_history ON {table}')
    schema_editor.execute('DROP FUNCTION bio_reject_history_change()')

class Migration(migrations.Migration):
    dependencies = [('webapp', '0001_initial')]
    operations = [migrations.RunPython(protect, unprotect)]
