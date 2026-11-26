# SPDX-License-Identifier: AGPL-3.0-only
"""Current-scope views of the official bracket and recorded game results."""

from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from backend.match_orchestrator import bracket as B, tiebreak as TB
from . import domain as D


def game_ref(state, game):
    return {
        'match_id': game['match_id'],
        'status': state['matches'][game['match_id']]['status'],
    }


@api_view(['GET'])
def bracket(request, tid):
    D.tournament(request.user, tid)
    state, brackets = D.bracket_for(tid)
    if not brackets:
        return Response({'tournament_id': tid, 'bracket': None})

    # The scheduler uses the tournament ID; older flows can have a different
    # bracket ID linked to the same tournament record.
    official = next((record for record in brackets if record['id'] == tid), brackets[0])
    view = B.public_view(official)
    view['map_pool_id'] = official.get('map_pool')
    for round_source, round_view in zip(official['rounds'], view['rounds']):
        for pairing, pairing_view in zip(round_source['matches'], round_view['matches']):
            sid = pairing['series_id']
            series = state.get('series', {}).get(sid)
            pairing_view['series'] = None if series is None else {
                'id': sid, 'status': series['status'],
                'games': [game_ref(state, game) for game in series['games']],
            }
    return Response({'tournament_id': tid, 'bracket': view})


def locate_match(state, mid):
    if mid not in state['matches']:
        raise NotFound()
    for bracket_record in state.get('brackets', {}).values():
        tid = bracket_record.get('tournament_id')
        if tid is None:
            continue
        for round_source in bracket_record['rounds']:
            for pairing in round_source['matches']:
                series = state.get('series', {}).get(pairing['series_id'])
                if series and any(game['match_id'] == mid for game in series['games']):
                    return tid, round_source['number'], series
    raise NotFound()


@api_view(['GET'])
def match_detail(request, mid):
    state = D.runtime().flow.store.snapshot()
    tid, round_number, series = locate_match(state, mid)
    D.tournament(request.user, tid)

    view = TB.public_view(series)
    for game, game_view in zip(series['games'], view['games']):
        # The worker replay reference does not establish current availability.
        del game_view['has_replay']
        game_view.update(game_ref(state, game))
    view['versions'] = {'A': series['submission_a'], 'B': series['submission_b']}
    view['tiebreak_maps'] = series['tiebreak_maps']
    return Response({'tournament_id': tid, 'match_id': mid, 'round_number': round_number, 'series': view})
