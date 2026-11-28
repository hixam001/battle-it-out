# SPDX-License-Identifier: AGPL-3.0-only
"""Current-scope views of the official bracket and recorded game results."""

from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from backend.match_orchestrator import bracket as B, orchestrator as O, replays as P, tiebreak as TB
from backend.notifications import sources as N
from backend.registration import registration as G
from backend.tournaments import tournaments as T
from . import domain as D


def game_ref(state, game):
    return {
        'match_id': game['match_id'],
        'status': state['matches'][game['match_id']]['status'],
    }


def series_wins(series):
    return {side: sum(game['winner_side'] == side for game in series['games']) for side in ('A', 'B')}


def add_notice_result_links(rt, recipient_id, items):
    """Resolve current result links for both existing and newly stored notices."""
    notices = {(item['tournament_id'], item['id']): item
               for item in items if item['event_type'] == 'match_result'}
    if not notices:
        return
    requested = {tid for tid, _ in notices}
    tournaments = rt.tournaments.store.snapshot()['tournaments']
    teams = {m['tournament_id']: m['team_id'] for m in G.memberships(rt.registration, recipient_id)
             if m['registration_status'] == G.REGISTERED and m['tournament_id'] in requested
             and tournaments.get(m['tournament_id'], {}).get('status', T.DELETED) != T.DELETED}
    if not teams:
        return
    state = rt.flow.store.snapshot()
    for bracket in state.get('brackets', {}).values():
        tid = bracket.get('tournament_id')
        team = teams.get(tid)
        if team is None:
            continue
        for rd in bracket['rounds']:
            for pairing in rd['matches']:
                if pairing['winner'] is None or pairing['bye'] or team not in (pairing['a'], pairing['b']):
                    continue
                nid = N.match_result_notice_id(bracket['id'], rd['number'], pairing['index'], team, recipient_id)
                notice = notices.get((tid, nid))
                series = state.get('series', {}).get(pairing['series_id'])
                if notice is not None and series and series['result'] and series['games']:
                    match_id = series['games'][-1]['match_id']
                    if match_id in state['matches']:
                        notice['result_match_id'] = match_id


def official_bracket(tid, brackets):
    # The scheduler uses the tournament ID; older flows can have a different
    # bracket ID linked to the same tournament record.
    return next((record for record in brackets if record['id'] == tid), brackets[0] if brackets else None)


@api_view(['GET'])
def bracket(request, tid):
    D.tournament(request.user, tid)
    state, brackets = D.bracket_for(tid)
    official = official_bracket(tid, brackets)
    if official is None:
        return Response({'tournament_id': tid, 'bracket': None})

    view = B.public_view(official)
    view['map_pool_id'] = official.get('map_pool')
    view['maps'] = {kind: official['maps'][kind] for kind in ('play', 'tiebreak_normal', 'tiebreak_final')}
    for round_source, round_view in zip(official['rounds'], view['rounds']):
        for pairing, pairing_view in zip(round_source['matches'], round_view['matches']):
            sid = pairing['series_id']
            series = state.get('series', {}).get(sid)
            pairing_view['series'] = None if series is None else {
                'id': sid, 'status': series['status'],
                'wins': series_wins(series),
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
    view['wins'] = series_wins(series)
    view['tiebreak_maps'] = series['tiebreak_maps']
    return Response({'tournament_id': tid, 'match_id': mid, 'round_number': round_number, 'series': view})


@api_view(['GET'])
def replay_status(request, mid):
    rt = D.runtime()
    state = rt.flow.store.snapshot()
    tid, _, _ = locate_match(state, mid)
    who, tournament = D.tournament(request.user, tid)
    if tournament['status'] == T.ARCHIVED:
        return Response({'status': 'archived'})

    viewer = P.Viewer(who.role, who.tournament_ids)
    try:
        replay = P.replay_status(rt.vault, mid, viewer, tournament_id=tid)
    except P.NotFound:
        game_status = state['matches'][mid]['status']
        status = 'unavailable' if game_status in (O.COMPLETED, O.BOT_FORFEIT) else 'pending'
    else:
        status = 'archived' if replay['status'] == P.PURGED else replay['status']
    return Response({'status': status})
