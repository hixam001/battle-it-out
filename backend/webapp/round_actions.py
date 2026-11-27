# SPDX-License-Identifier: AGPL-3.0-only
"""Current-scope tournament map selection, bracket generation and round start."""
import time
from zipfile import BadZipFile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.decorators import api_view, parser_classes
from rest_framework.exceptions import APIException, NotAuthenticated, NotFound, ValidationError
from rest_framework.parsers import JSONParser

from backend.match_orchestrator import bracket as B, maps as M, orchestrator as O
from backend.match_runner import launcher as L
from backend.notifications import sources as NS
from backend.registration import registration as G
from backend.submission_registry import registry as R
from backend.tournament_flow import flow as F
from backend.tournaments import scheduler as S, tournaments as T
from . import domain as D, results
from .views import body_fields, mutate, private


class EngineCatalogueUnavailable(APIException):
    status_code = 503


def locked_scope(request, tid):
    # The operator assignment command locks the same account before changing a grant.
    account = get_user_model().objects.select_for_update().filter(pk=request.user.pk, is_active=True).first()
    if account is None:
        raise NotAuthenticated()
    return D.tournament(account, tid, staff=True)


def conflict(message):
    return {'error': {'message': message}}


@api_view(['GET', 'PUT'])
@parser_classes([JSONParser])
def map_pool(request, tid):
    runtime = D.runtime()
    if request.method == 'GET':
        _, tournament = D.tournament(request.user, tid, staff=True)
        pools = runtime.flow.store.snapshot().get('map_pools', {})
        return private({'selected_id': tournament['map_pool_id'], 'version': tournament['version'],
                        'items': [{key: pool[key] for key in ('id', 'engine_version', 'maps')}
                                  for pool in sorted(pools.values(), key=lambda row: row['id'])]})
    with transaction.atomic():
        actor, tournament = locked_scope(request, tid)
        body = body_fields(request, ('map_pool_id', 'expected_version'), ('map_pool_id', 'expected_version'))
        pool_id, version = body['map_pool_id'], body['expected_version']
        if not isinstance(pool_id, str) or not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValidationError('Choose an existing map pool and provide a positive expected_version.')
        try:
            M.get_pool(runtime.flow.store, pool_id)
        except M.MapError as exc:
            raise ValidationError('Choose an existing map pool.') from exc
        if tournament['map_pool_id'] != pool_id and D.bracket_for(tid)[1]:
            return private(conflict('A generated bracket keeps its recorded map pool.'), 409)
        try:
            result = T.edit(runtime.tournaments, actor, tid, {'map_pool_id': pool_id}, expected_version=version)
        except T.Conflict as exc:
            return private(conflict(str(exc)), 409)
        except T.Invalid as exc:
            raise ValidationError(str(exc)) from exc
    return private({'selected_id': result['map_pool_id'], 'version': result['version']})


@api_view(['POST'])
@parser_classes([JSONParser])
def generate(request, tid):
    with transaction.atomic():
        actor, tournament = locked_scope(request, tid)
        body = body_fields(request, ('confirm',), ('confirm',))
        if body['confirm'] is not True:
            raise ValidationError('Bracket generation requires confirmation.')
        runtime = D.runtime()
        if tournament['status'] == T.RUNNING:
            stored = results.official_bracket(tid, D.bracket_for(tid)[1])
            if stored is not None:
                pins = runtime.flow.registry.store.snapshot()['pins'].get(tid, {}).get('teams', {})
                return private({'bracket': B.public_view(stored), 'excluded': sorted(team for team in pins if pins[team] is None)})
        if tournament['status'] != T.OPEN:
            return private(conflict('Registration must be open to generate a bracket.'), 409)
        if tournament['deadlines'][T.SUBMISSION] > time.time():
            return private(conflict('The submission deadline has not passed.'), 409)
        if settings.BIO_ENGINE_JAR is None:
            raise EngineCatalogueUnavailable()
        try:
            catalogue = M.load_engine_maps(settings.BIO_ENGINE_JAR)
        except (M.MapError, OSError, BadZipFile) as exc:
            raise EngineCatalogueUnavailable() from exc
        try:
            drawn = S.open_ready_bracket(
                runtime.tournaments, runtime.flow, tid,
                teams_of=lambda tournament_id: G.registered_teams(runtime.registration, tournament_id),
                tell=lambda tournament_id, excluded: NS.draw_exclusions(
                    runtime.notifications, runtime.registration, tournament_id, excluded),
                by=actor.user_id, catalogue=catalogue, engine_version=L.load_lock()['engine_version'],
            )
        except R.PendingChecks:
            return private(conflict('Wait for the pending submission checks before generating the bracket.'), 409)
        except (F.FlowError, B.BracketError, M.MapError, O.ConflictError, T.Conflict) as exc:
            return private(conflict(str(exc)), 409)
    return private({'bracket': B.public_view(drawn['bracket']), 'excluded': drawn['excluded']})


@api_view(['POST'])
@parser_classes([JSONParser])
def start(request, tid, round_number):
    D.tournament(request.user, tid, staff=True)
    body = body_fields(request, ('confirm', 'idempotency_key'), ('confirm', 'idempotency_key'))
    if body['confirm'] is not True or not isinstance(body['idempotency_key'], str):
        raise ValidationError('Round start requires confirmation and an idempotency key.')

    def action():
        actor, tournament = D.tournament(request.user, tid, staff=True)
        if tournament['status'] != T.RUNNING:
            return conflict('A round can start only in a running tournament.'), 409
        stored = results.official_bracket(tid, D.bracket_for(tid)[1])
        if stored is None or not 1 <= round_number <= len(stored['rounds']):
            raise NotFound()
        try:
            outcome = F.start_round(D.runtime().flow, stored['id'], round_number, actor.user_id, enqueue_paused=False)
        except B.BracketError as exc:
            return conflict(str(exc)), 409
        except F.FlowError:
            return conflict('The round cannot start until staff resolve the pinned submission issue.'), 409
        if outcome['round']['status'] == B.PAUSED:
            return conflict('This round is paused. Contact the tournament operator.'), 409
        return {'round_number': round_number, 'status': outcome['round']['status'], 'job_id': outcome['job']}, 200

    return mutate(request, tid, action, idempotency_key=body['idempotency_key'], staff=True)
