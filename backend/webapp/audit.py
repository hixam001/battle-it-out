# SPDX-License-Identifier: AGPL-3.0-only
"""Role-scoped read projection of existing audit records."""
import re
from heapq import nlargest

from django.db.models import CharField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T
from . import domain as D
from .models import AuditEvent, Dispute
from .views import private


PUBLIC_TOURNAMENT_ACTIONS = frozenset({
    'open_registration', 'extend_deadline', 'emergency_override', 'mark_running', 'mark_completed', 'archive',
})
DISPUTE_ACTIONS = ('dispute_opened', 'dispute_updated')
ORGANIZER_FEATURE_ACTIONS = (*DISPUTE_ACTIONS, 'submission_history_read', 'submission_validation_read')
DETAIL_TOKENS = {
    'tournament': ('from', 'to', 'status', 'deadline_type', 'setting'),
    'registration': ('team',),
    'submissions': ('submission_id', 'team_id', 'status', 'role'),
    'notifications': ('event_type',),
    'web': ('status', 'team_id', 'submission_id', 'user_id', 'dispute_id'),
}
DETAIL_NUMBERS = {
    'registration': ('created', 'updated', 'rejected', 'count'),
    'submissions': ('teams',),
    'notifications': ('created', 'attempts'),
    'web': ('version',),
}
DETAIL_FLAGS = {
    'tournament': ('replays_deleted',),
    'submissions': ('activated',),
}


def _token(value):
    return value if isinstance(value, str) and R.KEY_RE.fullmatch(value) else None


def _item(source, sequence, timestamp, tournament_id, action, actor, detail):
    safe = {key: detail[key] for key in DETAIL_TOKENS[source] if _token(detail.get(key))}
    safe.update({key: detail[key] for key in DETAIL_NUMBERS.get(source, ())
                 if type(detail.get(key)) is int})
    safe.update({key: detail[key] for key in DETAIL_FLAGS.get(source, ())
                 if type(detail.get(key)) is bool})
    item = {
        'id': f'{source}-{sequence}', 'source': source, 'action': action,
        'created_at': timestamp.isoformat(), 'tournament_id': tournament_id, 'detail': safe,
    }
    if _token(actor):
        item['actor_id'] = actor
    return (timestamp, source, sequence), item


def _web_rows(who, tid, window):
    query = AuditEvent.objects.all()
    if tid is not None:
        query = query.filter(tournament_id=tid)
    if who.role == 'organizer':
        query = query.filter(action__in=ORGANIZER_FEATURE_ACTIONS)
    elif who.role == 'participant':
        own_disputes = Dispute.objects.filter(tournament_id=tid, team_id__in=who.team_ids)
        own_dispute_ids = own_disputes.annotate(text_id=Cast('pk', CharField())).values('text_id')
        query = query.annotate(dispute_ref=KeyTextTransform('id', 'detail')).filter(
            action__in=DISPUTE_ACTIONS, dispute_ref__in=own_dispute_ids,
        )
    for event in query.order_by('-created_at', '-pk')[:window].iterator():
        detail = event.detail if isinstance(event.detail, dict) else {}
        if event.action in DISPUTE_ACTIONS:
            detail = {'dispute_id': detail.get('id'), 'status': detail.get('status'),
                      'version': detail.get('version')}
        yield _item('web', event.pk, event.created_at, event.tournament_id or None, event.action,
                    event.actor_id_text if who.role != 'participant' else None, detail)


def _legacy_rows(audit, source, who, tid, reference=None):
    for sequence, row in enumerate(audit):
        event_tid = row.get('tournament') or row.get('tournament_id')
        detail = row
        if reference is not None:
            resolved_tid, projected = reference(row)
            event_tid = event_tid or resolved_tid
            detail = {**row, **projected}
        if tid is not None and event_tid != tid:
            continue
        if who.role == 'participant':
            if source == 'tournament' and row['action'] not in PUBLIC_TOURNAMENT_ACTIONS:
                continue
            if source == 'submissions' and (
                detail.get('team_id') not in who.team_ids or row['action'] not in ('upload', 'verdict')
            ):
                continue
        timestamp = parse_datetime(row['at'])
        row_key, item = _item(source, sequence, timestamp, event_tid, row['action'],
                              row['actor'] if who.role != 'participant' else None, detail)
        if source == 'tournament' and _token(row.get('id')):
            item['id'] = row['id']
        yield row_key, item


def _rows(rt, who, tid, tournament_state, window):
    yield from _web_rows(who, tid, window)
    yield from _legacy_rows(tournament_state['audit'], 'tournament', who, tid)
    submissions = rt.flow.registry.store.snapshot()

    def submission_reference(row):
        rec = submissions['submissions'].get(row.get('submission_id'), {})
        return rec.get('tournament_id'), {'team_id': rec.get('team_id')}

    yield from _legacy_rows(submissions['audit'], 'submissions', who, tid, submission_reference)
    if who.role != 'participant':
        registration = rt.registration.store.snapshot()
        yield from _legacy_rows(registration['audit'], 'registration', who, tid)
        notices = rt.notifications.store.snapshot()

        def notice_reference(row):
            note = notices['notifications'].get(row.get('notification'), {})
            return note.get('tournament_id'), {}

        yield from _legacy_rows(notices['audit'], 'notifications', who, tid, notice_reference)


def _number(query, key, default, minimum, maximum):
    value = query.get(key, str(default))
    if not re.fullmatch(r'[0-9]{1,10}', value) or not minimum <= int(value) <= maximum:
        raise ValidationError(f'{key} must be a whole number from {minimum} to {maximum}.')
    return int(value)


def _page(request, who, tid, *, global_audit=False):
    query = request.query_params
    allowed = {'limit', 'offset', 'tournament_id'} if global_audit else {'limit', 'offset'}
    if set(query) - allowed or any(len(query.getlist(key)) != 1 for key in query):
        raise ValidationError('Unsupported or repeated audit query parameters.')
    limit = _number(query, 'limit', 50, 1, 200)
    offset = _number(query, 'offset', 0, 0, 2_147_483_647)
    if 'tournament_id' in query:
        tid = query['tournament_id']
        if not R.TOURNAMENT_ID_RE.fullmatch(tid):
            raise ValidationError('tournament_id must be a valid tournament ID.')
    rt = D.runtime()
    window = offset + limit + 1
    rows = _rows(rt, who, tid, rt.tournaments.store.snapshot(), window)
    newest = nlargest(window, rows, key=lambda row: row[0])
    return private({'items': [row[1] for row in newest[offset:offset + limit]],
                    'next_offset': offset + limit if len(newest) > offset + limit else None})


@api_view(['GET'])
def tournament_audit(request, tid):
    who, record = D.tournament(request.user, tid)
    if who.role == 'participant' and record['status'] not in (T.OPEN, T.RUNNING, T.COMPLETED, T.ARCHIVED):
        raise NotFound()
    return _page(request, who, tid)


@api_view(['GET'])
def admin_audit(request):
    who = D.actor(request.user)
    if who.role != 'admin':
        raise PermissionDenied('Admin access is required.')
    return _page(request, who, None, global_audit=True)
