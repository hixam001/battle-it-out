# SPDX-License-Identifier: AGPL-3.0-only
"""Session-scoped tournament drafts, settings and approval transitions."""
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, parser_classes
from rest_framework.exceptions import APIException, NotAuthenticated, NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser

from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T
from . import domain as D
from .models import AuditEvent, OrganizerAssignment
from .views import body_fields, private, timestamp


DEADLINES = ('registration_deadline', 'submission_deadline')
SETTINGS = ('name', 'description', *DEADLINES)
PARTICIPANT_STATUSES = (T.OPEN, T.RUNNING, T.COMPLETED, T.ARCHIVED)
TRANSITIONS = {
    'submit-for-approval': (T.submit_for_approval, ('organizer',), ()),
    'approve': (T.approve, ('admin',), ('confirm',)),
    'reject': (T.reject, ('admin',), ('reason',)),
    'open-registration': (T.open_registration, ('admin', 'organizer'), ()),
}


class StateConflict(APIException):
    status_code = 409


@contextmanager
def tournament_errors():
    try:
        yield
    except T.NotFound as exc:
        raise NotFound() from exc
    except T.Forbidden as exc:
        raise PermissionDenied(str(exc)) from exc
    except T.Invalid as exc:
        raise ValidationError(str(exc)) from exc
    except T.Conflict as exc:
        raise StateConflict(str(exc)) from exc


def locked_account(request):
    # Operator assignment changes serialize on the same account row.
    user = get_user_model().objects.select_for_update().filter(pk=request.user.pk, is_active=True).first()
    if user is None:
        raise NotAuthenticated()
    return user


def read_settings(data):
    settings = dict(data)
    for field in DEADLINES:
        if field in settings:
            settings[field] = timestamp(settings[field], field)
    return settings


def detail_view(record):
    detail = dict(record)
    for field in DEADLINES:
        try:
            detail[field] = datetime.fromtimestamp(record[field], UTC).isoformat().replace('+00:00', 'Z')
        except (ValueError, OverflowError, OSError):
            # Legacy library callers can store epoch values outside the datetime range.
            detail[field] = None
    return detail


def list_tournaments(user):
    who = D.actor(user)
    rt = D.runtime()
    items = []
    for record in rt.tournaments.store.snapshot()['tournaments'].values():
        tid = record['id']
        if record['status'] == T.DELETED or (who.role != 'admin' and tid not in who.tournament_ids):
            continue
        if who.role == 'participant' and record['status'] not in PARTICIPANT_STATUSES:
            continue
        teams = who.team_ids & set(G.registered_teams(rt.registration, tid)) if who.team_ids else ()
        items.append({**{key: record[key] for key in ('id', 'name', 'description', 'status', 'deadlines')},
                      'teams': sorted(teams), 'captain_teams': sorted(who.captain_of.intersection(teams))})
    return private({'items': items, 'role': who.role})


def assign_creator(user, tid):
    assignments = OrganizerAssignment.objects.filter(user=user, tournament_id=tid)
    if assignments.filter(active=True).exists():
        return
    if assignments.exists():
        raise NotFound()
    OrganizerAssignment.objects.create(user=user, tournament_id=tid)
    AuditEvent.objects.create(actor_id_text=str(user.pk), tournament_id=tid, action='organizer_assigned',
                              detail={'user_id': str(user.pk), 'reason': 'Tournament created'})


@api_view(['GET', 'POST'])
@parser_classes([JSONParser])
def tournaments(request):
    if request.method == 'GET':
        return list_tournaments(request.user)
    with tournament_errors(), transaction.atomic():
        user = locked_account(request)
        who = D.actor(user)
        if who.role not in ('admin', 'organizer'):
            raise PermissionDenied('Tournament staff access is required.')
        data = read_settings(body_fields(request, SETTINGS, SETTINGS))
        key = request.headers.get('Idempotency-Key', '')
        if not R.KEY_RE.fullmatch(key):
            raise ValidationError('A safe Idempotency-Key of 1–128 characters is required.')
        # The same request keeps its ID across a retry, including after a database commit failure.
        tid = uuid5(NAMESPACE_URL, f'battle-it-out:tournament:{user.pk}:{key}').hex
        if who.role == 'organizer':
            assign_creator(user, tid)
        record = T.create(D.runtime().tournaments, who, tid, **data, idempotency_key=key)
        if record['status'] == T.DELETED:
            raise NotFound()
    return private(detail_view(record), 201)


def revision(data):
    version = data['expected_version']
    if type(version) is not int or version < 1:
        raise ValidationError('expected_version must be a positive whole number.')
    return version


@api_view(['GET', 'PATCH'])
@parser_classes([JSONParser])
def tournament(request, tid):
    reg = D.runtime().tournaments
    with tournament_errors():
        if request.method == 'GET':
            who, _ = D.tournament(request.user, tid)
            record = T.get(reg, who, tid)
            if record['status'] == T.DELETED:
                raise NotFound()
            return private(detail_view(record))
        with transaction.atomic():
            who, _ = D.tournament(locked_account(request), tid, staff=True)
            data = read_settings(body_fields(request, (*SETTINGS, 'expected_version'), ('expected_version',)))
            version = revision(data)
            del data['expected_version']
            record = T.edit(reg, who, tid, data, expected_version=version)
    return private(detail_view(record))


@api_view(['POST'])
@parser_classes([JSONParser])
def transition(request, tid, action):
    change, roles, fields = TRANSITIONS[action]
    with tournament_errors(), transaction.atomic():
        who, _ = D.tournament(locked_account(request), tid, staff=True)
        if who.role not in roles:
            raise PermissionDenied('This tournament action is unavailable to your role.')
        fields = (*fields, 'expected_version')
        data = body_fields(request, fields, fields)
        revision(data)
        record = change(D.runtime().tournaments, who, tid, **data)
    return private(detail_view(record))
