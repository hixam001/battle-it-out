# SPDX-License-Identifier: AGPL-3.0-only
"""Current staff scope for the existing official roster operations."""
import io

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, parser_classes
from rest_framework.exceptions import (
    APIException, NotAuthenticated, NotFound, ParseError, PermissionDenied, ValidationError,
)
from rest_framework.parsers import BaseParser, JSONParser, MultiPartParser

from backend.registration import registration as G
from backend.submission_registry import registry as R
from . import domain as D
from .views import body_fields, private


class RosterTooLarge(APIException):
    status_code = 413
    default_detail = 'The roster exceeds the interim 1 MiB limit.'


class RosterJSONParser(BaseParser):
    media_type = JSONParser.media_type

    def parse(self, stream, media_type=None, parser_context=None):
        raw = stream.read(G.MAX_CSV_BYTES + 1)
        if len(raw) > G.MAX_CSV_BYTES:
            raise RosterTooLarge()
        try:
            return JSONParser().parse(io.BytesIO(raw), media_type, parser_context)
        except RecursionError as exc:
            raise ParseError('The roster must be a JSON object containing rows.') from exc


def _apply(request, tid, action, *, write=False):
    who, _ = D.tournament(request.user, tid, staff=True)
    registration = D.runtime().registration
    try:
        if write:
            with transaction.atomic():
                users = get_user_model().objects.select_for_update()
                current = users.filter(pk=request.user.pk, is_active=True).first()
                if current is None:
                    raise NotAuthenticated()
                who, _ = D.tournament(current, tid, staff=True)
                result = action(registration, who)
        else:
            result = action(registration, who)
        return private(result)
    except G.NotFound as exc:
        raise NotFound() from exc
    except G.Forbidden as exc:
        raise PermissionDenied() from exc
    except G.Invalid as exc:
        raise ValidationError(str(exc)) from exc
    except G.Conflict as exc:
        return private({'error': {'message': str(exc)}}, 409)


def _import_rows(request):
    if request.content_type.partition(';')[0].strip().lower() == 'multipart/form-data':
        if set(request.data) != {'file'} or len(request.data.getlist('file')) != 1 or 'file' not in request.FILES:
            raise ValidationError('Upload one roster CSV file.')
        raw = request.FILES['file'].read(G.MAX_CSV_BYTES + 1)
        if len(raw) > G.MAX_CSV_BYTES:
            raise RosterTooLarge()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValidationError('The roster CSV must use UTF-8 encoding.') from exc
        return G.parse_csv(text), 'roster.csv'
    data = body_fields(request, ('rows',), ('rows',))
    return data['rows'], 'roster.json'


@api_view(['GET'])
def roster(request, tid):
    return _apply(request, tid, lambda reg, who: {'items': G.list_roster(reg, who, tid)})


@api_view(['GET'])
def report(request, tid):
    return _apply(request, tid, lambda reg, who: G.report(reg, who, tid))


@api_view(['POST'])
@parser_classes([RosterJSONParser, MultiPartParser])
def import_roster(request, tid):
    def action(reg, who):
        key = request.headers.get('Idempotency-Key', '')
        if not R.KEY_RE.fullmatch(key):
            raise ValidationError('A safe Idempotency-Key of 1–128 characters is required.')
        rows, filename = _import_rows(request)
        return G.import_roster(reg, who, tid, rows, source_filename=filename, idempotency_key=key)

    return _apply(request, tid, action, write=True)


@api_view(['PATCH'])
@parser_classes([RosterJSONParser])
def correct_entry(request, tid, entry_id):
    def action(reg, who):
        fields = ('email', 'team_key', 'team_name', 'member_number', 'role_label', 'expected_version')
        data = body_fields(request, fields, ('expected_version',))
        version = data['expected_version']
        if type(version) is not int or version < 1:
            raise ValidationError('expected_version must be a positive whole number.')
        return G.correct_entry(reg, who, tid, entry_id,
                               {k: v for k, v in data.items() if k != 'expected_version'},
                               expected_version=version)

    return _apply(request, tid, action, write=True)
