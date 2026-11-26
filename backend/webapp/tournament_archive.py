# SPDX-License-Identifier: AGPL-3.0-only
"""Archive a completed tournament through the service's private replay vault."""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, parser_classes
from rest_framework.exceptions import NotAuthenticated, NotFound, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from backend.tournaments import tournaments as T
from . import domain as D


@api_view(['POST'])
@parser_classes([JSONParser])
def archive(request, tid):
    # provision_access takes the same user lock before changing an assignment.
    # Keep the current grant stable while the archive transition is admitted.
    with transaction.atomic():
        users = get_user_model().objects.select_for_update()
        current = users.filter(pk=request.user.pk, is_active=True).first()
        if current is None:
            raise NotAuthenticated()
        actor, _ = D.tournament(current, tid, staff=True)
        body = request.data
        if not isinstance(body, dict) or set(body) != {'confirm'} or body['confirm'] is not True:
            raise ValidationError('Archiving requires {"confirm":true}.')
        runtime = D.runtime()
        try:
            result = T.archive(runtime.tournaments, actor, tid, runtime.vault, confirm=True)
        except T.NotFound as exc:
            raise NotFound() from exc
        except T.Conflict as exc:
            return Response({'error': {'message': str(exc)}}, status=409)
    return Response(result)
