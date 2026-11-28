# SPDX-License-Identifier: AGPL-3.0-only
import csv
import hashlib
import io
import json
import os
import re
import stat
import time
from datetime import UTC, datetime, timedelta
from django.apps import apps
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.db import connections, transaction
from django.http import FileResponse, JsonResponse, HttpResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from psycopg import OperationalError, connect
from rest_framework.decorators import api_view, permission_classes, parser_classes, renderer_classes
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.exceptions import NotFound, PermissionDenied, UnsupportedMediaType, ValidationError
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from backend.match_orchestrator import replays as P
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.submission_bundle import bundle as BU
from backend.tournament_flow import flow as F
from backend.work_queue import jobs as J
from backend.notifications import notifications as N
from backend.tournaments import tournaments as T
from . import domain as D
from .models import AuditEvent, Dispute, DisputeEvent, LoginAttempt, Receipt


def private(body, status=200):
    response = Response(body, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


@require_http_methods(['GET', 'HEAD'])
def health(request):
    """Process liveness only: no accounts, database, legacy stores or engine work."""
    return JsonResponse({'status': 'ok'})


@require_http_methods(['GET', 'HEAD'])
def readiness(request):
    """Probe the application schema with the web service's credentials."""
    params = connections['default'].get_connection_params()
    options = params.get('options') or ''
    params.update(connect_timeout=3, options=f'{options} -c statement_timeout=2000', autocommit=True)
    tables = [model._meta.db_table for model in apps.get_models(include_auto_created=True)
              if model._meta.managed and not model._meta.proxy]
    try:
        with connect(**params) as probe, probe.cursor() as cursor:
            cursor.execute('SELECT bool_and(pg_catalog.to_regclass(name) IS NOT NULL) '
                           'FROM unnest(%s::text[]) AS expected(name)', (tables,))
            if not cursor.fetchone()[0]:
                return JsonResponse({}, status=503)
    except OperationalError:
        return JsonResponse({}, status=503)
    return JsonResponse({'status': 'ready'})


@ensure_csrf_cookie
@require_http_methods(['GET'])
def session(request):
    user = request.user
    response = JsonResponse({'csrf': get_token(request), 'user': {'id': user.pk, 'username': user.username,
                             'admin': user.is_superuser} if user.is_authenticated and user.is_active else None})
    response['Cache-Control'] = 'private, no-store'
    return response


@csrf_protect
@require_http_methods(['POST'])
def login_view(request):
    if request.content_type != 'application/json':
        return JsonResponse({'error': {}}, status=415)
    try:
        body = json.loads(request.body)
        if not isinstance(body, dict) or set(body) != {'username', 'password'} \
                or not all(isinstance(v, str) and 0 < len(v) <= 256 for v in body.values()):
            raise ValueError()
    except (ValueError, UnicodeError):
        return JsonResponse({'error': {'message': 'Enter a username and password.'}}, status=400)
    # Durable per-source/account limiter. Values themselves are never stored or returned.
    keys = sorted(hashlib.sha256(value.encode()).hexdigest() for value in
                  ('source\0' + request.META.get('REMOTE_ADDR', ''), 'account\0' + body['username'].casefold()))
    since = timezone.now() - timedelta(minutes=15)
    with transaction.atomic():
        # Independently bound source and account attempts, including unknown names; stable lock order.
        from django.db import connection
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                for key in keys:
                    cursor.execute('SELECT pg_advisory_xact_lock(%s)', [int(key[:15], 16)])
        LoginAttempt.objects.filter(at__lt=since).delete()
        if any(LoginAttempt.objects.filter(key=key, at__gte=since).count() >= 10 for key in keys):
            return JsonResponse({'error': {'message': 'Too many attempts. Try again later.'}}, status=429)
        LoginAttempt.objects.bulk_create([LoginAttempt(key=key) for key in keys])
    user = authenticate(request, username=body['username'], password=body['password'])
    if user is None:
        return JsonResponse({'error': {'message': 'Invalid username or password.'}}, status=401)
    login(request, user)
    response = JsonResponse({'csrf': get_token(request), 'user': {'id': user.pk, 'username': user.username, 'admin': user.is_superuser}})
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['POST'])
def logout_view(request):
    logout(request)
    return private({'status': 'logged_out'})


@api_view(['GET'])
def team_profile(request, tid, team):
    who, _ = D.tournament(request.user, tid)
    try:
        profile = G.team_view(D.runtime().registration, who, tid, team)
    except G.NotFound as exc:
        raise NotFound() from exc
    return private(profile)


@api_view(['GET'])
@permission_classes([AllowAny])
def dependencies(request):
    return Response({'items': BU.dependency_catalogue(), 'max_files': BU.MAX_FILES, 'max_bytes': BU.MAX_BYTES})


@api_view(['GET'])
def analytics(request, tid):
    D.tournament(request.user, tid)
    return private(D.analytics(tid))


@api_view(['GET'])
def analytics_csv(request, tid):
    D.tournament(request.user, tid)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['team', 'played', 'wins', 'losses', 'byes', 'win_rate'])
    for row in D.analytics(tid)['teams']:
        # Defence against spreadsheet formulas even if a trusted legacy store has unexpected text.
        values = [row[k] for k in ('team', 'played', 'wins', 'losses', 'byes', 'win_rate')]
        writer.writerow(["'" + x if isinstance(x, str) and x.startswith(('=', '+', '-', '@', '\t', '\r')) else x for x in values])
    response = HttpResponse(output.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="tournament-analytics.csv"'
    response['Cache-Control'] = 'private, no-store'
    return response


def safe_board(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return None
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            return None
        data = json.loads(raw)
        numeric = ('width', 'height', 'round', 'updated_at', 'finished')
        if not isinstance(data, dict) or any(not isinstance(data.get(k), (int, float, bool)) for k in numeric):
            return None
        if not 1 <= data['width'] <= 256 or not 1 <= data['height'] <= 256:
            return None
        result = {k: data[k] for k in numeric}
        for key, fields, cap in (('robots', ('id', 'x', 'y', 'team', 'kind', 'health', 'cheese', 'dir'), 10000),
                                 ('walls', ('x', 'y'), 65536), ('dirt', ('x', 'y'), 65536), ('cheese', ('x', 'y'), 65536),
                                 ('teams', ('team', 'cheese_transferred', 'cat_damage', 'alive_kings', 'alive_rats'), 2)):
            values = data.get(key, [])
            if not isinstance(values, list) or len(values) > cap:
                return None
            result[key] = [{field: row.get(field, 0) for field in fields} for row in values
                           if isinstance(row, dict) and all(isinstance(row.get(field, 0), (int, float)) for field in fields)]
        return result
    except (OSError, ValueError, TypeError):
        return None


@api_view(['GET'])
def live(request, tid):
    who, record = D.tournament(request.user, tid)
    if record['status'] == 'archived':
        return private({'error': {'message': 'Live boards are unavailable after archive.'}}, 410)
    state, brackets = D.bracket_for(tid)
    matches = []
    for b in brackets:
        for rd in b['rounds']:
            for m in rd['matches']:
                series = state.get('series', {}).get(m.get('series_id'))
                if not series:
                    continue
                game = state['matches'][series['games'][-1]['match_id']]
                board = safe_board(D.runtime().config.data_dir / 'live' / (game['id'] + '.json'))
                matches.append({'series_id': series['id'], 'match_id': game['id'], 'round': rd['number'],
                                'a': series['team_a'], 'b': series['team_b'],
                                'status': series['status'], 'game_status': game['status'], 'map': game['map'],
                                'winner': (series.get('result') or {}).get('winner_team'), 'board': board})
    return private({'items': matches, 'poll_after_ms': 1000})


class ReplayDownloadRenderer(JSONRenderer):
    # FileResponse streams the download. DRF uses this renderer only for errors
    # when the client asks for binary, and middleware normalizes those to JSON.
    media_type = 'application/octet-stream'
    format = P.REPLAY_FORMAT


@api_view(['GET'])
@renderer_classes([JSONRenderer, ReplayDownloadRenderer])
def replay(request, mid):
    who = D.actor(request.user)
    viewer = P.Viewer(who.role, who.tournament_ids)
    rt = D.runtime()
    tid = P.replay_tournament(rt.vault, mid, viewer)
    with rt.tournaments.store.transaction() as state:
        tournament = state['tournaments'].get(tid)
        if not tournament or tournament['status'] == T.DELETED:
            raise NotFound()
        if tournament['status'] == T.ARCHIVED:
            raise P.Gone('The tournament is archived.')
    handle, stream = P.open_replay(rt.vault, mid, viewer, tournament_id=tid)
    try:
        return FileResponse(stream, as_attachment=True, filename=f'{handle.match_id}.{P.REPLAY_FORMAT}',
                            content_type='application/octet-stream')
    except BaseException:
        stream.close()
        raise


def body_fields(request, allowed, required):
    if not isinstance(request.data, dict) or set(request.data) - set(allowed) or set(required) - set(request.data):
        raise ValidationError('Missing or unsupported fields.')
    return request.data


def timestamp(value, field):
    message = f'{field} must be an ISO 8601 timestamp with a timezone.'
    if not isinstance(value, str) or len(value) > 64:
        raise ValidationError(message)
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(UTC).timestamp()
    except (ValueError, OverflowError, OSError) as exc:
        raise ValidationError(message) from exc


@api_view(['GET'])
def notifications(request):
    who = D.notification_recipient(request.user)
    query = request.query_params
    allowed = {'limit', 'offset', 'unread_only', 'tournament_id'}
    if set(query) - allowed or any(len(query.getlist(key)) != 1 for key in query):
        raise ValidationError('Unsupported or repeated query parameters.')

    def integer(key, default, minimum, maximum):
        value = query.get(key, str(default))
        if not re.fullmatch(r'[0-9]{1,10}', value) or not minimum <= int(value) <= maximum:
            raise ValidationError(f'{key} must be a whole number from {minimum} to {maximum}.')
        return int(value)

    unread = query.get('unread_only', 'false')
    if unread not in ('true', 'false'):
        raise ValidationError('unread_only must be true or false.')
    return private(N.list_notifications(
        D.runtime().notifications, who, unread_only=unread == 'true',
        tournament_id=query.get('tournament_id'),
        limit=integer('limit', 50, 1, N.MAX_PAGE), offset=integer('offset', 0, 0, 2_147_483_647)))


@api_view(['PATCH'])
@parser_classes([JSONParser])
def notification_detail(request, nid):
    who = D.notification_recipient(request.user)
    body = body_fields(request, {'read'}, {'read'})
    return private(N.mark_read(D.runtime().notifications, who, nid, read=body['read']))


@api_view(['GET', 'PATCH'])
@parser_classes([JSONParser])
def notification_preferences(request):
    who = D.notification_recipient(request.user)
    center = D.runtime().notifications
    if request.method == 'GET':
        return private(N.get_preferences(center, who))
    return private(N.update_preferences(center, who, request.data))


def text(body, key, limit):
    value = body.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
        raise ValidationError(f'{key} must be nonempty text of at most {limit} characters.')
    return value.strip()


def mutate(request, tid, action, *, idempotency_key=None, staff=False):
    key = request.headers.get('Idempotency-Key', '') if idempotency_key is None else idempotency_key
    if not isinstance(key, str) or not R.KEY_RE.fullmatch(key):
        raise ValidationError('A safe Idempotency-Key of 1–128 characters is required.')
    fingerprint = hashlib.sha256(json.dumps([request.method, request.path, request.data], sort_keys=True, default=str).encode()).hexdigest()
    with transaction.atomic():
        current_user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        request.user.is_active, request.user.is_superuser = current_user.is_active, current_user.is_superuser
        D.tournament(request.user, tid, staff=staff)  # current scope, including before stored-response delivery
        receipt = Receipt.objects.filter(user=request.user, key=key).first()
        if receipt:
            if receipt.fingerprint != fingerprint:
                return private({'error': {'message': 'This key was used for another request.'}}, 409)
            return private(receipt.body, receipt.status_code)
        result, code = action()
        Receipt.objects.create(user=request.user, key=key, fingerprint=fingerprint, body=result, status_code=code)
        return private(result, code)


@api_view(['GET', 'POST'])
@parser_classes([MultiPartParser])
def submissions(request, tid, team):
    who, _ = D.tournament(request.user, tid)
    rt = D.runtime()
    if request.method == 'GET':
        try:
            items = R.history(rt.flow.registry, who, team, tournament_id=tid)
        except R.NotFound:
            # A roster team can legitimately have no registry entry yet.
            try:
                G.team_view(rt.registration, who, tid, team)
            except G.NotFound as exc:
                raise NotFound() from exc
            items = []
        references = D.submission_match_ids(tid, (item['id'] for item in items))
        for item in items:
            item['match_ids'] = references[item['id']]
        if who.role in ('organizer', 'admin'):
            AuditEvent.objects.create(actor_id_text=who.user_id, tournament_id=tid,
                                      action='submission_history_read', detail={'team_id': team})
        return private({'items': items})
    if who.role == 'participant':
        if team not in who.team_ids or team not in G.registered_teams(rt.registration, tid):
            raise NotFound('No such team.')
    if who.role != 'participant' or team not in who.captain_of:
        raise PermissionDenied('Only this team’s captain may upload.')
    if request.content_type.partition(';')[0].strip().lower() != 'multipart/form-data':
        raise UnsupportedMediaType(request.content_type)
    if set(request.data) != {'file'} or len(request.data.getlist('file')) != 1 or 'file' not in request.FILES:
        raise ValidationError('Upload one bot.py or Python bundle ZIP as file.')
    key = request.headers.get('Idempotency-Key', '')
    if not R.KEY_RE.fullmatch(key):
        raise ValidationError('A safe Idempotency-Key of 1–128 characters is required.')
    upload = request.FILES['file']
    is_bundle = upload.name.endswith('.zip')
    limit = min(rt.flow.registry.max_bytes, BU.MAX_BYTES) if is_bundle else rt.flow.registry.max_bytes
    raw = upload.read(limit + 1)
    if len(raw) > limit:
        return private({'error': {'message': f'Upload is larger than {limit} bytes.'}}, 413)
    if not is_bundle and upload.name != R.STORED_NAME:
        return private({'error': {'message': 'Name the Python file bot.py, or upload a Python bundle ZIP.'}}, 422)
    # Hold the tournament lock while storing the version against its current deadline.
    try:
        with rt.tournaments.store.transaction() as state:
            record = state['tournaments'].get(tid)
            if not record or record['status'] == T.DELETED:
                raise NotFound('No such tournament.')
            result = F.upload(rt.flow, who, team, tid, upload.name, raw, bundle=is_bundle,
                              idempotency_key=key, deadline_at=record['deadlines'][T.SUBMISSION])
    except BU.TooLarge as exc:
        return private({'error': {'message': str(exc)}}, 413)
    except BU.Invalid as exc:
        return private({'error': {'message': str(exc)}}, 422)
    static = result['validations'][0]
    if static['status'] == 'rejected':
        reasons = static['reasons']
        return private({'error': {'message': reasons[0]['message'],
                                  'details': {'submission_id': result['id'], 'reasons': reasons}}}, 422)
    del result['check_job']
    return private(result, 201)


@api_view(['GET'])
def submission_validation(request, tid, sid):
    who, _ = D.tournament(request.user, tid)
    report = R.validation_report(D.runtime().flow.registry, who, sid, tournament_id=tid)
    if who.role in ('organizer', 'admin'):
        AuditEvent.objects.create(actor_id_text=who.user_id, tournament_id=tid,
                                  action='submission_validation_read', detail={'submission_id': sid})
    return private(report)


@api_view(['GET'])
def download(request, tid, sid):
    who, _ = D.tournament(request.user, tid)
    rt = D.runtime()
    rec = rt.flow.registry.store.snapshot()['submissions'].get(sid)
    if not rec or rec['tournament_id'] != tid:
        raise NotFound('No such submission.')
    if 'bundle_files' in rec:
        data = R.download_bundle(rt.flow.registry, who, sid)
        content_type, filename = 'application/zip', 'bot-bundle.zip'
    else:
        handle = R.download(rt.flow.registry, who, sid)
        data = R._read_regular(handle.path, handle.size)
        if hashlib.sha256(data).hexdigest() != handle.sha256:
            raise R.Unavailable('Stored source changed.')
        content_type, filename = 'text/x-python', 'bot.py'
    response = FileResponse(io.BytesIO(data), as_attachment=True, filename=filename, content_type=content_type)
    response['Cache-Control'] = 'private, no-store'
    return response


def dispute_view(item, detail=False):
    result = {k: getattr(item, k) for k in ('tournament_id', 'series_id', 'team_id', 'title', 'status', 'version', 'resolution')}
    result.update(id=str(item.id), created_at=item.created_at.isoformat(), updated_at=item.updated_at.isoformat())
    if detail:
        result['description'] = item.description
        result['events'] = [{'kind': e.kind, 'body': e.body, 'created_at': e.created_at.isoformat()} for e in item.events.order_by('pk')]
    return result


def visible_disputes(who, tid):
    query = Dispute.objects.filter(tournament_id=tid)
    return query if who.role in ('admin', 'organizer') else query.filter(team_id__in=who.team_ids)


@api_view(['GET', 'POST'])
def disputes(request, tid):
    who, record = D.tournament(request.user, tid)
    if request.method == 'GET':
        return private({'items': [dispute_view(d) for d in visible_disputes(who, tid).order_by('-created_at')[:200]]})
    body = body_fields(request, ('series_id', 'title', 'description'), ('series_id', 'title', 'description'))
    series = D.series_for(tid, text(body, 'series_id', 128))
    if who.role != 'participant' or not (who.team_ids & {series['team_a'], series['team_b']}):
        raise PermissionDenied('A registered member of a team in this match may open a dispute.')
    title, description = text(body, 'title', 160), text(body, 'description', 4000)
    def action():
        current, _ = D.tournament(request.user, tid)
        team = sorted(current.team_ids & {series['team_a'], series['team_b']})
        if not team:
            raise PermissionDenied('Team membership is required.')
        item = Dispute.objects.create(tournament_id=tid, series_id=series['id'], team_id=team[0],
                                      opened_by=request.user, title=title, description=description)
        DisputeEvent.objects.create(dispute=item, actor=request.user, kind='opened', body='Dispute opened.')
        AuditEvent.objects.create(actor_id_text=str(request.user.pk), tournament_id=tid, action='dispute_opened', detail={'id': str(item.id)})
        return dispute_view(item, True), 201
    return mutate(request, tid, action)


@api_view(['GET', 'POST'])
def dispute_detail(request, tid, did):
    who, record = D.tournament(request.user, tid)
    item = visible_disputes(who, tid).filter(pk=did).first()
    if not item:
        raise NotFound('No such dispute.')
    if request.method == 'GET':
        return private(dispute_view(item, True))
    body = body_fields(request, ('expected_version', 'message', 'status', 'resolution'), ('expected_version',))
    def action():
        current, _ = D.tournament(request.user, tid)
        item = visible_disputes(current, tid).select_for_update().get(pk=did)
        version = body['expected_version']
        if isinstance(version, bool) or not isinstance(version, int) or version != item.version:
            return {'error': {'message': 'The dispute changed. Reload before editing.'}}, 409
        if item.status in ('resolved', 'rejected'):
            return {'error': {'message': 'This dispute is closed.'}}, 409
        if 'status' in body:
            if current.role not in ('admin', 'organizer'):
                raise PermissionDenied('Only assigned staff may change review status.')
            target = body['status']
            transitions = {'open': {'reviewing', 'rejected'}, 'reviewing': {'awaiting_participant', 'resolved', 'rejected'},
                           'awaiting_participant': {'reviewing', 'resolved', 'rejected'}}
            if not isinstance(target, str) or target not in transitions.get(item.status, set()):
                raise ValidationError('Invalid review transition.')
            reason = text(body, 'resolution', 4000)
            item.status, item.resolution = target, reason
            DisputeEvent.objects.create(dispute=item, actor=request.user, kind='status_changed', body=reason)
        elif 'message' in body and 'resolution' not in body:
            DisputeEvent.objects.create(dispute=item, actor=request.user, kind='comment', body=text(body, 'message', 4000))
        else:
            raise ValidationError('Provide a comment or a staff status change with a reason.')
        item.version += 1
        item.save()
        AuditEvent.objects.create(actor_id_text=str(request.user.pk), tournament_id=tid, action='dispute_updated', detail={'id': str(item.id), 'version': item.version, 'status': item.status})
        return dispute_view(item, True), 200
    return mutate(request, tid, action)


@api_view(['GET'])
def operations(request):
    if not request.user.is_superuser:
        raise PermissionDenied('Admin access is required.')
    rt = D.runtime()
    incidents = []
    for kind, store in (('matches', rt.flow.store), ('queue', rt.flow.queue.store), ('replays', rt.vault.index)):
        for inc in store.snapshot()['incidents']:
            if inc['status'] == 'open':
                incidents.append({'source': kind, **{k: inc.get(k) for k in ('id', 'incident_type', 'job_id', 'match_id', 'tournament_id', 'attempt_count', 'alerted_admin_at')}})
    return private({'status': rt.status(), 'incidents': incidents,
                    'dead_jobs': [{k: j[k] for k in ('id', 'kind', 'failures')} for j in J.list_jobs(rt.flow.queue, J.DEAD)],
                    'audit': [{'action': a.action, 'tournament_id': a.tournament_id, 'created_at': a.created_at.isoformat(), 'detail': a.detail}
                              for a in AuditEvent.objects.order_by('-pk')[:100]]})
