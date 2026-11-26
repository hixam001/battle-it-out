# SPDX-License-Identifier: AGPL-3.0-only
"""Operator-only account/roster link or Organizer assignment; no public grant route."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from backend.registration import registration as G
from backend.webapp import domain as D
from backend.webapp.models import Identity, OrganizerAssignment, AuditEvent

class Command(BaseCommand):
    help = 'Link an existing Django account to a verified roster identity, or assign/revoke an Organizer.'
    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--roster-user-id')
        parser.add_argument('--organizer-tournament')
        parser.add_argument('--revoke', action='store_true')
        parser.add_argument('--reason', required=True)
    def handle(self, **options):
        if not options['reason'].strip() or len(options['reason']) > 500:
            raise CommandError('A reason of 1–500 characters is required')
        if bool(options['roster_user_id']) == bool(options['organizer_tournament']):
            raise CommandError('Choose exactly one roster identity or Organizer tournament')
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(username=options['username'], is_active=True)
            if user.is_superuser:
                raise CommandError('A superuser already has global access; do not mix scoped roles')
            identity = Identity.objects.filter(user=user).first()
            if options['roster_user_id']:
                if options['revoke']:
                    raise CommandError('Roster membership revocation requires the account-deletion lifecycle; it is not an assignment revoke')
                actor = G.actor_for(D.runtime().registration, options['roster_user_id'])
                try:
                    email = G.normalize_email(user.email)
                except G.Invalid:
                    raise CommandError('Account email must match a verified official roster identity') from None
                if not actor.tournament_ids or G.official_email(D.runtime().registration, options['roster_user_id']) != email:
                    raise CommandError('Account email must match a verified official roster identity')
                if identity and identity.roster_user_id and identity.roster_user_id != actor.user_id:
                    raise CommandError('An existing roster identity link cannot be replaced by this command')
                if Identity.objects.filter(roster_user_id=actor.user_id).exclude(user=user).exists():
                    raise CommandError('This roster identity is already linked to another account')
                if identity and identity.role != 'participant':
                    raise CommandError('Role composition is unresolved; create separate staff/participant accounts')
                Identity.objects.update_or_create(user=user, defaults={'role': 'participant', 'roster_user_id': actor.user_id})
                action = 'roster_identity_linked'
                tid = ''
            else:
                tid = options['organizer_tournament']
                if tid not in D.runtime().tournaments.store.snapshot()['tournaments']:
                    raise CommandError('No such tournament')
                if identity and identity.role != 'organizer':
                    raise CommandError('Role composition is unresolved; create separate staff/participant accounts')
                Identity.objects.update_or_create(user=user, defaults={'role': 'organizer', 'roster_user_id': None})
                existing = OrganizerAssignment.objects.filter(user=user, tournament_id=tid, active=True)
                if options['revoke']:
                    existing.update(active=False)
                    action = 'organizer_revoked'
                else:
                    if not existing.exists():
                        OrganizerAssignment.objects.create(user=user, tournament_id=tid)
                    action = 'organizer_assigned'
            AuditEvent.objects.create(actor_id_text='operator', tournament_id=tid, action=action,
                                      detail={'user_id': str(user.pk), 'reason': options['reason']})
        self.stdout.write('Access updated; current requests use the new scope.')
