# SPDX-License-Identifier: AGPL-3.0-only
"""Current server-derived scope and allowlisted projections of existing authoritative stores."""
import math
import statistics
from django.conf import settings
from rest_framework.exceptions import NotFound, PermissionDenied
from backend.services.runner import Config, Runtime
from backend.submission_registry import registry as R
from backend.registration import registration as G
from .models import Identity, OrganizerAssignment

def runtime():
    return Runtime(Config(settings.BIO_DATA_DIR, settings.BIO_DATA_DIR / 'unused.jar', '3.15'))

def actor(user):
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied('Sign in to continue.')
    if user.is_superuser:
        return R.Actor(str(user.pk), 'admin')
    identity = Identity.objects.filter(user=user).first()
    if not identity:
        return R.Actor(str(user.pk), 'participant')
    if identity.role == 'organizer':
        tids = frozenset(OrganizerAssignment.objects.filter(user=user, active=True).values_list('tournament_id', flat=True))
        return R.Actor(str(user.pk), 'organizer', tournament_ids=tids)
    return G.actor_for(runtime().registration, identity.roster_user_id) if identity.roster_user_id else R.Actor(str(user.pk), 'participant')

def notification_recipient(user):
    """Legacy inbox IDs are roster IDs, never Django account primary keys.

    Staff/global account inbox provisioning is not implemented. Require the
    explicit operator-created participant link instead of guessing an ID.
    Personal notices remain readable independently of current tournament scope.
    """
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied('Sign in to continue.')
    identity = Identity.objects.filter(user=user, role='participant').first()
    if not identity or not identity.roster_user_id or user.is_superuser:
        raise PermissionDenied('A linked participant account is required for notifications.')
    return R.Actor(identity.roster_user_id, 'participant')

def tournament(user, tid, *, staff=False):
    who = actor(user)
    record = runtime().tournaments.store.snapshot()['tournaments'].get(tid)
    if not record or record['status'] == 'deleted' or (who.role != 'admin' and tid not in who.tournament_ids):
        raise NotFound('No such tournament.')
    if staff and who.role not in ('admin', 'organizer'):
        raise PermissionDenied('Tournament staff access is required.')
    return who, record

def bracket_for(tid):
    state = runtime().flow.store.snapshot()
    brackets = [b for b in state.get('brackets', {}).values() if b.get('tournament_id') == tid]
    return state, brackets

def series_for(tid, sid):
    state, brackets = bracket_for(tid)
    for bracket in brackets:
        for rd in bracket['rounds']:
            for match in rd['matches']:
                if match.get('series_id') == sid and sid in state.get('series', {}):
                    return state['series'][sid]
    raise NotFound('No such match.')

def analytics(tid):
    state, brackets = bracket_for(tid)
    teams, maps, rounds, versions, durations = {}, {}, [], {}, []
    totals = {'teams': 0, 'pairings': 0, 'completed': 0, 'byes': 0, 'coin_flips': 0,
              'forfeits': 0, 'games': 0, 'platform_failures': 0, 'bot_failures': 0}
    for bracket in brackets:
        for entry in bracket['teams']:
            teams.setdefault(entry['team'], {'team': entry['team'], 'played': 0, 'wins': 0, 'losses': 0, 'byes': 0})
        for rd in bracket['rounds']:
            completed = 0
            for match in rd['matches']:
                if match['bye']:
                    totals['byes'] += 1
                    teams[match['a']]['byes'] += 1
                    continue
                totals['pairings'] += 1
                series = state.get('series', {}).get(match.get('series_id'))
                if not series:
                    continue
                result = series.get('result')
                if result:
                    completed += 1
                    totals['completed'] += 1
                    totals['coin_flips'] += result['result_type'] == 'coin_flip'
                    totals['forfeits'] += result['result_type'] == 'bot_forfeit'
                    for key, label in (('winner_team', 'wins'), ('loser_team', 'losses')):
                        teams[result[key]]['played'] += 1
                        teams[result[key]][label] += 1
                for played in series.get('games', []):
                    game = state['matches'][played['match_id']]
                    row = maps.setdefault(game['map'], {'map': game['map'], 'games': 0, 'ties': 0, 'attempts': 0})
                    row['games'] += bool(game['attempts'])
                    row['attempts'] += len(game['attempts'])
                    row['ties'] += played.get('outcome') == 'tied'
                    for side, team_key, submission_key in (('A', 'team_a', 'submission_a'), ('B', 'team_b', 'submission_b')):
                        ref = game[submission_key]
                        version = versions.setdefault(ref, {'team': game[team_key], 'submission': ref, 'games': 0, 'wins': 0, 'ties': 0, 'forfeits': 0})
                        version['games'] += played.get('outcome') is not None
                        version['wins'] += played.get('outcome') in ('decided', 'forfeit') and played.get('winner_side') == side
                        version['ties'] += played.get('outcome') == 'tied'
                        version['forfeits'] += played.get('outcome') == 'forfeit' and played.get('winner_side') != side
                    totals['games'] += bool(game['attempts'])
                    for attempt in game['attempts']:
                        totals['platform_failures'] += attempt['status'] == 'platform_failed'
                        totals['bot_failures'] += attempt['status'] == 'bot_failed'
                        seconds = (attempt.get('summary') or {}).get('seconds')
                        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and math.isfinite(seconds) and seconds >= 0:
                            durations.append(seconds)
            rounds.append({'number': rd['number'], 'status': rd['status'], 'completed': completed})
    totals['teams'] = len(teams)
    for row in teams.values():
        row['win_rate'] = round(row['wins'] / row['played'], 4) if row['played'] else None
    durations.sort()
    latency = {'samples': len(durations), 'median_seconds': round(statistics.median(durations), 3) if durations else None,
               'p95_seconds': round(durations[max(0, math.ceil(len(durations) * .95) - 1)], 3) if durations else None}
    return {'totals': totals, 'latency': latency, 'versions': sorted(versions.values(), key=lambda v: (v['team'], v['submission'])), 'teams': sorted(teams.values(), key=lambda x: (-x['wins'], x['team'])),
            'maps': sorted(maps.values(), key=lambda x: x['map']), 'rounds': rounds}
