# SPDX-License-Identifier: AGPL-3.0-only
"""Response-boundary regressions; all fixtures are test-only URLs."""
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import DatabaseError, connections
from django.http import Http404, JsonResponse
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import path
from psycopg import connect, sql
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.permissions import AllowAny

from backend.submission_bundle import bundle as BU
from backend.submission_registry import registry as R
from .urls import urlpatterns as application_urls


def returned_error(request, status):
    response = JsonResponse({'error': {'message': 'Fixture explanation', 'details': {'field': ['Fixture detail']}}}, status=status)
    response['Retry-After'] = '7'
    response['Content-Length'] = str(len(response.content))
    return response


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def raised_error(request, kind):
    errors = {
        'missing': Http404('private fixture path'),
        'forbidden': DjangoPermissionDenied('fixture private staff diagnostic'),
        'fields': ValidationError({'title': ['Enter a title.']}),
        'text': ValidationError('Provide a comment or a staff status change with a reason.'),
        'throttle': Throttled(wait=12),
        'bundle': BU.Invalid('The archive must contain bot.py.'),
        'registry-missing': R.NotFound('private fixture path'),
        'registry-forbidden': R.Forbidden('private fixture path'),
        'registry-conflict': R.Conflict('private fixture path'),
        'registry-large': R.TooLarge('private fixture path'),
        'registry-unavailable': R.Unavailable('private fixture path'),
        'bug': ValueError('fixture secret database password and path'),
        'database': DatabaseError('fixture private SQL'),
    }
    if kind == 'parse':
        return JsonResponse({'parsed': request.data})
    raise errors[kind]


urlpatterns = application_urls + [
    path('api/v1/_returned/<int:status>/', returned_error),
    path('api/v1/_raised/<str:kind>/', raised_error),
    path('outside-api/', returned_error, {'status': 409}),
]


class FailingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raise RuntimeError('fixture private middleware diagnostic')


@override_settings(ROOT_URLCONF=__name__)
class HTTPContract(SimpleTestCase):
    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response['Content-Type'], 'application/json')
        error = response.json()['error']
        self.assertEqual(set(error), {'code', 'message', 'details', 'request_id'})
        self.assertEqual(error['code'], code)
        self.assertIsInstance(error['message'], str)
        self.assertIsInstance(error['details'], dict)
        self.assertRegex(error['request_id'], r'^req_[0-9a-f]{32}$')
        self.assertEqual(error['request_id'], response['X-Request-ID'])
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        if hasattr(response, 'data'):
            self.assertEqual(response.data, response.json())
        return error

    def test_direct_errors_share_contract_codes_and_keep_retry_headers(self):
        # Expectations come from API_CONTRACT, independently of the mapping under test.
        for status, code in (
            (400, 'VALIDATION_ERROR'), (401, 'UNAUTHENTICATED'), (403, 'FORBIDDEN'),
            (404, 'NOT_FOUND'), (405, 'METHOD_NOT_ALLOWED'), (406, 'NOT_ACCEPTABLE'),
            (409, 'STATE_CONFLICT'), (410, 'EXPIRED'), (413, 'FILE_TOO_LARGE'),
            (415, 'UNSUPPORTED_MEDIA_TYPE'), (422, 'BOT_VALIDATION_FAILED'),
            (429, 'RATE_LIMITED'), (500, 'INTERNAL_ERROR'), (503, 'SERVICE_UNAVAILABLE'),
        ):
            with self.subTest(status=status):
                response = self.client.get(f'/api/v1/_returned/{status}/')
                error = self.assert_error(response, status, code)
                self.assertEqual(response['Retry-After'], '7')
                self.assertEqual(int(response['Content-Length']), len(response.content))
                if status >= 500 or status == 404:
                    self.assertNotIn('Fixture', response.content.decode())
                    self.assertEqual(error['details'], {})
                else:
                    self.assertEqual(error['details'], {'field': ['Fixture detail']})

    def test_unknown_status_keeps_status_and_uses_safe_fallback(self):
        response = self.client.get('/api/v1/_returned/502/')
        self.assert_error(response, 502, 'INTERNAL_ERROR')
        self.assertNotIn(b'Fixture', response.content)

    def test_request_ids_are_fresh_and_ignore_incoming_header(self):
        first = self.client.get('/api/v1/health/', HTTP_X_REQUEST_ID='caller-supplied')
        second = self.client.get('/api/v1/health/', HTTP_X_REQUEST_ID=first['X-Request-ID'])
        self.assertRegex(first['X-Request-ID'], r'^req_[0-9a-f]{32}$')
        self.assertNotEqual(first['X-Request-ID'], second['X-Request-ID'])

    def test_health_is_public_and_has_no_database_or_runtime_dependency(self):
        # SimpleTestCase forbids database queries. A failing runtime constructor
        # also proves this doesn't initialize or write any legacy stores.
        with patch('backend.webapp.domain.runtime', side_effect=AssertionError('runtime touched')):
            for path_ in ('/api/v1/health/', '/api/v1/health/?format=anything'):
                response = self.client.get(path_)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'status': 'ok'})
                self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertEqual(self.client.head('/api/v1/health/').content, b'')
        self.assert_error(self.client.post('/api/v1/health/'), 405, 'METHOD_NOT_ALLOWED')

    def test_django_and_drf_wrong_methods_preserve_allow(self):
        for url, method, allowed in (
            ('/api/v1/ready/', 'post', 'HEAD'),
            ('/api/v1/auth/session/', 'post', 'GET'),
            ('/api/v1/dependencies/', 'post', 'GET'),
            ('/api/v1/auth/login/', 'get', 'POST'),
        ):
            response = getattr(self.client, method)(url)
            self.assert_error(response, 405, 'METHOD_NOT_ALLOWED')
            self.assertIn(allowed, response['Allow'])

    def test_resolver_404_is_generic_even_in_debug(self):
        for debug in (False, True):
            with self.subTest(debug=debug), override_settings(DEBUG=debug):
                response = self.client.get('/api/v1/no-such-private-thing/')
                self.assert_error(response, 404, 'NOT_FOUND')
                self.assertNotIn(b'no-such-private-thing', response.content)

    def test_exception_mappings_and_private_library_messages(self):
        for kind, status, code in (
            ('missing', 404, 'NOT_FOUND'), ('forbidden', 403, 'FORBIDDEN'),
            ('registry-missing', 404, 'NOT_FOUND'), ('registry-forbidden', 403, 'FORBIDDEN'),
            ('registry-conflict', 409, 'STATE_CONFLICT'), ('registry-large', 413, 'FILE_TOO_LARGE'),
            ('registry-unavailable', 503, 'SERVICE_UNAVAILABLE'),
        ):
            with self.subTest(kind=kind):
                response = self.client.get(f'/api/v1/_raised/{kind}/')
                self.assert_error(response, status, code)
                self.assertNotIn(b'private fixture path', response.content)
                self.assertNotIn(b'private staff diagnostic', response.content)

    def test_validation_keeps_actionable_text_and_field_structure(self):
        for kind, message in (
            ('text', 'Provide a comment or a staff status change with a reason.'),
            ('bundle', 'The archive must contain bot.py.'),
        ):
            response = self.client.get(f'/api/v1/_raised/{kind}/')
            self.assertEqual(self.assert_error(response, 400, 'VALIDATION_ERROR')['message'], message)
        response = self.client.get('/api/v1/_raised/fields/')
        self.assertEqual(self.assert_error(response, 400, 'VALIDATION_ERROR')['details'], {'title': ['Enter a title.']})

    def test_throttling_keeps_retry_after(self):
        response = self.client.get('/api/v1/_raised/throttle/')
        self.assert_error(response, 429, 'RATE_LIMITED')
        self.assertEqual(response['Retry-After'], '12')

    def test_malformed_json_and_unsupported_media_type(self):
        response = self.client.post('/api/v1/_raised/parse/', data='{', content_type='application/json')
        self.assert_error(response, 400, 'VALIDATION_ERROR')
        response = self.client.post('/api/v1/_raised/parse/', data='text', content_type='text/plain')
        self.assert_error(response, 415, 'UNSUPPORTED_MEDIA_TYPE')
        response = self.client.post('/api/v1/auth/login/', data='text', content_type='text/plain')
        self.assert_error(response, 415, 'UNSUPPORTED_MEDIA_TYPE')

    def test_login_validation_failures_have_the_same_envelope(self):
        for body in ('{', '[]', '{}', json.dumps({'username': 'u', 'password': ''})):
            self.assert_error(self.client.post('/api/v1/auth/login/', data=body, content_type='application/json'), 400, 'VALIDATION_ERROR')

    def test_django_csrf_failure_is_json_and_does_not_reflect_reason(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post('/api/v1/auth/login/', data='{}', content_type='application/json', HTTP_ORIGIN='https://untrusted-fixture.example')
        self.assert_error(response, 403, 'FORBIDDEN')
        self.assertIn('CSRF verification failed', response.json()['error']['message'])
        self.assertNotIn(b'untrusted-fixture', response.content)

    def test_unexpected_errors_are_redacted_500_and_still_reach_django_logs(self):
        client = Client(raise_request_exception=False)
        for debug in (False, True):
            for kind in ('bug', 'database'):
                with self.subTest(debug=debug, kind=kind), override_settings(DEBUG=debug), self.assertLogs('django.request', level='ERROR'):
                    response = client.get(f'/api/v1/_raised/{kind}/')
                error = self.assert_error(response, 500, 'INTERNAL_ERROR')
                self.assertEqual(error['details'], {})
                self.assertNotIn(b'fixture', response.content)
                self.assertNotIn(b'Traceback', response.content)

    @override_settings(MIDDLEWARE=[
        'backend.webapp.api_errors.APIResponseMiddleware',
        'backend.webapp.tests_http.FailingMiddleware',
    ])
    def test_downstream_middleware_failure_keeps_json_contract(self):
        client = Client(raise_request_exception=False)
        response = client.get('/api/v1/health/')
        self.assert_error(response, 500, 'INTERNAL_ERROR')
        self.assertNotIn(b'private middleware diagnostic', response.content)

    def test_content_negotiation_failure_is_json(self):
        response = self.client.get('/api/v1/dependencies/', HTTP_ACCEPT='text/html')
        self.assert_error(response, 406, 'NOT_ACCEPTABLE')

    def test_public_dependency_catalogue_has_pinned_metadata(self):
        response = self.client.get('/api/v1/dependencies/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'items': [{
                'name': 'biohelpers',
                'version': '1.0.0',
                'sha256': 'a3a967470f89dd839fd246eebdff795f2d1e404f4f56f7c494d70c9c9b6d9cf8',
                'description': 'Grid distances and numeric clamping',
            }],
            'max_files': 32,
            'max_bytes': 262144,
        })

    def test_completion_log_contains_only_status_and_correlation_id(self):
        with self.assertLogs('backend.webapp.api_errors', level='WARNING') as logs:
            response = self.client.get('/api/v1/private-token-in-path/')
        self.assertIn(response['X-Request-ID'], logs.output[0])
        self.assertIn('404', logs.output[0])
        self.assertNotIn('private-token-in-path', logs.output[0])

    def test_non_api_responses_are_untouched(self):
        response = self.client.get('/outside-api/')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['message'], 'Fixture explanation')
        self.assertNotIn('X-Request-ID', response)


class PostgresReadiness(TestCase):
    def test_ready_queries_postgresql_without_using_session_or_runtime(self):
        with patch('backend.webapp.domain.runtime', side_effect=AssertionError('runtime touched')):
            response = self.client.get('/api/v1/ready/')
            head = self.client.head('/api/v1/ready/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ready'})
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertFalse(response.cookies)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b'')
        self.assertNotEqual(head['X-Request-ID'], response['X-Request-ID'])

    def test_unreachable_postgresql_returns_redacted_503_then_recovers(self):
        db = connections['default']
        with TemporaryDirectory() as empty_socket_dir:
            params = {**db.get_connection_params(), 'host': empty_socket_dir}
            with patch.object(db, 'get_connection_params', return_value=params):
                response = self.client.get('/api/v1/ready/')
                head = self.client.head('/api/v1/ready/')
                health = self.client.get('/api/v1/health/')
            self.assertNotIn(empty_socket_dir, response.content.decode())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        error = response.json()['error']
        self.assertEqual(error['code'], 'SERVICE_UNAVAILABLE')
        self.assertEqual(error['details'], {})
        self.assertEqual(error['request_id'], response['X-Request-ID'])
        self.assertEqual(head.status_code, 503)
        self.assertEqual(head.content, b'')
        self.assertEqual(health.status_code, 200)
        self.assertEqual(self.client.get('/api/v1/ready/').status_code, 200)

    def test_reachable_postgresql_without_app_tables_is_not_ready(self):
        db = connections['default']
        # The disposable server can answer SQL, but the app's migrated tables
        # are outside this connection's schema search path.
        params = {**db.get_connection_params(), 'options': '-c search_path=pg_catalog'}
        with patch.object(db, 'get_connection_params', return_value=params):
            response = self.client.get('/api/v1/ready/')
            head = self.client.head('/api/v1/ready/')
            health = self.client.get('/api/v1/health/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'SERVICE_UNAVAILABLE')
        self.assertEqual(response.json()['error']['details'], {})
        self.assertNotIn(b'pg_catalog', response.content)
        self.assertEqual(head.status_code, 503)
        self.assertEqual(head.content, b'')
        self.assertEqual(health.status_code, 200)
        self.assertEqual(self.client.get('/api/v1/ready/').status_code, 200)

    def test_readiness_requires_the_history_triggers_on_the_visible_tables(self):
        db = connections['default']
        params = db.get_connection_params()
        schema = 'bio_readiness_fixture'
        shadow = sql.Identifier(schema)
        # Use empty tables on the disposable search path. The real history
        # and its triggers remain intact throughout the fixture.
        with connect(**params, autocommit=True) as probe, probe.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE SCHEMA {}').format(shadow))
            try:
                for table in ('webapp_auditevent', 'webapp_disputeevent'):
                    name = sql.Identifier(table)
                    cursor.execute(sql.SQL('CREATE TABLE {}.{} (LIKE {})').format(shadow, name, name))
                current = cursor.execute('SHOW search_path').fetchone()[0]
                shadow_params = {**params, 'options': f'-c search_path={schema},{current.replace(" ", "")}'}
                with patch.object(db, 'get_connection_params', return_value=shadow_params):
                    response = self.client.get('/api/v1/ready/')
                    head = self.client.head('/api/v1/ready/')
                    health = self.client.get('/api/v1/health/')
            finally:
                cursor.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(shadow))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'SERVICE_UNAVAILABLE')
        self.assertEqual(response.json()['error']['details'], {})
        self.assertNotIn(schema, response.content.decode())
        self.assertEqual(head.status_code, 503)
        self.assertEqual(head.content, b'')
        self.assertEqual(health.status_code, 200)
        self.assertEqual(self.client.get('/api/v1/ready/').status_code, 200)
