# SPDX-License-Identifier: AGPL-3.0-only
"""Publish tournament announcements to the existing participant inbox and outbox."""
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, parser_classes
from rest_framework.exceptions import NotAuthenticated
from rest_framework.parsers import JSONParser

from backend.notifications import notifications as N
from . import domain as D
from .views import body_fields, private


@api_view(['POST'])
@parser_classes([JSONParser])
def publish(request, tid):
    D.tournament(request.user, tid, staff=True)
    fields = {'headline', 'message'}
    data = body_fields(request, fields, fields)
    runtime = D.runtime()
    # Use the same user lock as provision_access to serialize assignment
    # revocation with publication, including a retry of a stored receipt.
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().filter(pk=request.user.pk, is_active=True).first()
        if user is None:
            raise NotAuthenticated()
        actor, _ = D.tournament(user, tid, staff=True)
        result = N.publish_announcement(runtime.notifications, runtime.registration, actor, tid, data,
                                        idempotency_key=request.headers.get('Idempotency-Key', ''))
    return private(result, 201)
