# SPDX-License-Identifier: AGPL-3.0-only
"""Admin deadline changes with durable participant notices."""
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, parser_classes
from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser

from backend.notifications import sources as NS
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournaments import tournaments as T
from . import domain as D
from .views import body_fields, private


def _admin(user, tid):
    actor, _ = D.tournament(user, tid)
    if actor.role != 'admin':
        raise PermissionDenied('An Admin session is required.')
    return actor


def _timestamp(value):
    message = 'new_deadline must be an ISO 8601 timestamp with a timezone.'
    if not isinstance(value, str) or len(value) > 64:
        raise ValidationError(message)
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError) as exc:
        raise ValidationError(message) from exc


def _require_unpinned(rt, tid):
    if tid in rt.flow.registry.store.snapshot()['pins']:
        raise T.Conflict('Entry versions are already pinned for the draw.')


def _delivery_request(rt, tid, key, *, require_unpinned):
    def before_change():
        if require_unpinned:
            _require_unpinned(rt, tid)

    return T.NoticeRequest(key, lambda: G.account_ids(rt.registration, tid), before_change)


def _extend(rt, admin, tid, data, key):
    notice_request = _delivery_request(rt, tid, key, require_unpinned=True)
    return T.extend_deadline(rt.tournaments, admin, tid, data['deadline_type'],
                             _timestamp(data['new_deadline']), data['reason'],
                             confirm=True, notice_request=notice_request)


def _override(rt, admin, tid, data, key):
    setting, value = data['setting'], data['value']
    if setting == 'map_pool_id' and isinstance(value, str):
        if value not in rt.flow.store.snapshot().get('map_pools', {}):
            raise ValidationError('Select an existing map pool.')
    notice_request = _delivery_request(rt, tid, key, require_unpinned=setting == 'map_pool_id')
    return T.emergency_override(rt.tournaments, admin, tid, setting, value, data['reason'],
                                confirm=True, notice_request=notice_request)


def _apply(request, tid, fields, action):
    _admin(request.user, tid)
    fields = fields | {'confirm', 'reason'}
    data = body_fields(request, fields, fields)
    if data['confirm'] is not True:
        raise ValidationError('Confirm this deadline action with confirm=true.')
    key = request.headers.get('Idempotency-Key', '')
    if not R.KEY_RE.fullmatch(key):
        raise ValidationError('A safe Idempotency-Key of 1–128 characters is required.')
    rt = D.runtime()
    try:
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().filter(pk=request.user.pk).first()
            if user is None:
                raise NotAuthenticated()
            result = action(rt, _admin(user, tid), tid, data, key)
    except T.NotFound as exc:
        raise NotFound() from exc
    except T.Invalid as exc:
        raise ValidationError(str(exc)) from exc
    except T.Conflict as exc:
        return private({'error': {'message': str(exc)}}, 409)

    event_id = result['notification_event_id']
    pending = NS.publish_deadline_notices(rt.tournaments, rt.registration, rt.notifications, event_id=event_id)
    return private({**result, 'notification_status': 'pending' if pending else 'published'})


@api_view(['POST'])
@parser_classes([JSONParser])
def extend_deadline(request, tid):
    return _apply(request, tid, {'deadline_type', 'new_deadline'}, _extend)


@api_view(['POST'])
@parser_classes([JSONParser])
def emergency_override(request, tid):
    return _apply(request, tid, {'setting', 'value'}, _override)
