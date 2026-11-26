# SPDX-License-Identifier: AGPL-3.0-only
import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q

class Identity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    role = models.CharField(max_length=16, choices=[('participant', 'Participant'), ('organizer', 'Organizer')])
    roster_user_id = models.CharField(max_length=128, unique=True, null=True, blank=True)

class OrganizerAssignment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tournament_id = models.CharField(max_length=128)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'tournament_id'], condition=Q(active=True), name='one_live_assignment')]

class Dispute(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tournament_id = models.CharField(max_length=128)
    series_id = models.CharField(max_length=128)
    team_id = models.CharField(max_length=80)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=160)
    description = models.TextField()
    status = models.CharField(max_length=24, default='open')
    version = models.PositiveIntegerField(default=1)
    resolution = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class DisputeEvent(models.Model):
    dispute = models.ForeignKey(Dispute, on_delete=models.PROTECT, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=24)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class AuditEvent(models.Model):
    actor_id_text = models.CharField(max_length=128)
    tournament_id = models.CharField(max_length=128, blank=True)
    action = models.CharField(max_length=80)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

class Receipt(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    key = models.CharField(max_length=128)
    fingerprint = models.CharField(max_length=64)
    body = models.JSONField()
    status_code = models.PositiveSmallIntegerField()
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'key'], name='one_request_receipt')]

class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, db_index=True)
    at = models.DateTimeField(auto_now_add=True)
