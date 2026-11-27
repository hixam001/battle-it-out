# SPDX-License-Identifier: AGPL-3.0-only
"""Serve role-filtered, integrity-checked logs for official games."""
import hashlib
import os
import re
import stat
from contextlib import ExitStack
from pathlib import Path

from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, ValidationError

from backend.match_runner import match_log as L
from . import domain as D
from .results import locate_match
from .views import private


MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_NAME = re.compile(r'match-\d{8}-\d{6}\.events\.jsonl\Z')
DIGEST = re.compile(r'[a-f0-9]{64}\Z')
FIELDS = {
    'match.start': ('map', 'teams', 'engine_version', 'seed', 'limits_profile'),
    'match.result': ('outcome', 'classification', 'winner', 'loser', 'round', 'reason', 'retryable'),
    'match.end': (),
    'team.usage': ('team', 'turns', 'inits', 'longest_turn_ms', 'longest_init_ms', 'total_turn_ms',
                   'uncaught_exceptions', 'game_action_exceptions'),
    'team.output': ('team', 'entries_total', 'entries_omitted_in_middle', 'entries'),
    'team.failure': ('team', 'cause', 'kind', 'measured', 'limit', 'unit', 'round', 'detail'),
    'platform.diagnostics': ('classification_kind', 'gradle_exit', 'runner_exit',
                             'runner_exit_early', 'timed_out', 'seconds', 'rounds_per_second'),
}


def _published_attempt(match, requested):
    for attempt in reversed(match['attempts']):
        if requested is not None and attempt['number'] != requested:
            continue
        info = (attempt.get('summary') or {}).get('structured_log')
        if isinstance(info, dict) and 'path' in info:
            return attempt, info
    raise NotFound()


def _read(root, mid, number, info):
    components = ('out', 'matches', mid, f'attempt-{number}')
    path = Path(info['path'])
    if path.absolute().parent != root.absolute().joinpath(*components) or not LOG_NAME.fullmatch(path.name):
        raise ValueError('unexpected match log path')
    size, sha256 = info['bytes'], info['sha256']
    if type(size) is not int or not 0 < size <= MAX_LOG_BYTES or not DIGEST.fullmatch(sha256):
        raise ValueError('invalid log integrity metadata')
    with ExitStack() as stack:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        directory = os.open(root, directory_flags)
        stack.callback(os.close, directory)
        for component in components:
            directory = os.open(component, directory_flags, dir_fd=directory)
            stack.callback(os.close, directory)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != size:
                raise ValueError('unexpected match log file')
            raw = stream.read(size + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError('match log failed integrity verification')
    return L.parse_jsonl(raw.decode('utf-8'))


def _belongs_to_attempt(events, mid, attempt, info):
    return (len(events) == info['events'] and bool(events)
            and events[0].get('event') == 'match.start' and events[-1].get('event') == 'match.end'
            and all(row.get('match_id') == mid and row.get('attempt') == attempt['number']
                    and row.get('trace_id') == attempt['trace_id'] and row.get('seq') == sequence
                    and isinstance(row.get('data'), dict) and isinstance(row.get('event'), str)
                    for sequence, row in enumerate(events)))


def _project(events):
    for event in events:
        name = event['event']
        if name not in FIELDS:
            continue
        fields = FIELDS[name]
        yield {**{key: event[key] for key in ('seq', 'event', 'visibility', 'ts') if key in event},
               'data': {key: event['data'][key] for key in fields if key in event['data']}}


@api_view(['GET'])
def match_logs(request, mid):
    if mid in ('.', '..') or not L.REF_RE.fullmatch(mid):
        raise NotFound()
    rt = D.runtime()
    state = rt.flow.store.snapshot()
    tid, _, _ = locate_match(state, mid)
    who, _ = D.tournament(request.user, tid)
    match = state['matches'][mid]
    side = None
    if who.role == 'participant':
        side = next((s for s in ('A', 'B') if match['team_' + s.lower()] in who.team_ids), None)
        if side is None:
            raise NotFound()
    query = request.query_params
    if set(query) - {'attempt'} or len(query.getlist('attempt')) > 1:
        raise ValidationError('Unsupported or repeated match log query parameter.')
    selected = query.get('attempt')
    if selected is not None and not re.fullmatch(r'(?:[1-9][0-9]?|100)', selected):
        raise ValidationError('attempt must be a whole number from 1 to 100.')
    attempt, info = _published_attempt(match, int(selected) if selected is not None else None)
    try:
        events = _read(rt.config.data_dir, mid, attempt['number'], info)
        if not _belongs_to_attempt(events, mid, attempt, info):
            raise ValueError('match log belongs to another attempt')
    except (OSError, KeyError, TypeError, ValueError, RecursionError):
        return private({'error': {}}, 503)
    return private({
        'match_id': mid, 'tournament_id': tid, 'attempt': attempt['number'],
        'items': list(_project(L.view(events, who.role, side))),
    })
