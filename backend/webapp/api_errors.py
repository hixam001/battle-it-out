# SPDX-License-Identifier: AGPL-3.0-only
"""Shared API errors and per-request correlation across Django and DRF (CN-029)."""
import json
import logging
import uuid

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import JsonResponse
from rest_framework.exceptions import (
    APIException, NotAuthenticated, NotFound, PermissionDenied, ValidationError,
)
from rest_framework.views import exception_handler as drf_exception_handler

from backend.submission_bundle import bundle as BU
from backend.submission_registry import registry as R


logger = logging.getLogger(__name__)
ERRORS = {
    400: ('VALIDATION_ERROR', 'The request could not be understood.'),
    401: ('UNAUTHENTICATED', 'Sign in to continue.'),
    403: ('FORBIDDEN', 'This action is not available to your account.'),
    404: ('NOT_FOUND', 'The requested resource was not found.'),
    405: ('METHOD_NOT_ALLOWED', 'This method is not allowed for this resource.'),
    406: ('NOT_ACCEPTABLE', 'Request an application/json response.'),
    409: ('STATE_CONFLICT', 'The resource changed or the operation conflicts with its current state.'),
    410: ('EXPIRED', 'This resource is no longer available.'),
    413: ('FILE_TOO_LARGE', 'The upload exceeds the allowed size.'),
    415: ('UNSUPPORTED_MEDIA_TYPE', 'This request media type is not supported.'),
    422: ('BOT_VALIDATION_FAILED', 'The bot did not pass validation.'),
    429: ('RATE_LIMITED', 'Too many attempts. Try again later.'),
    500: ('INTERNAL_ERROR', 'The request could not be completed.'),
    503: ('SERVICE_UNAVAILABLE', 'The service is temporarily unavailable. Try again later.'),
}


def error_body(status, body, request_id):
    code, message = ERRORS.get(status, ERRORS[500] if status >= 500 else ERRORS[400])
    details = {}
    # Only structured application errors supply wording. Framework HTML and all
    # server failures get fixed text, even with DEBUG enabled. Hidden resources
    # share identical wording whether absent or outside the caller's scope.
    error = body.get('error') if isinstance(body, dict) else None
    if status < 500 and status != 404 and isinstance(error, dict):
        if isinstance(error.get('message'), str):
            message = error['message'][:1000]
        if isinstance(error.get('details'), dict):
            details = error['details']
    if message.startswith('CSRF Failed:'):
        message = 'CSRF verification failed. Refresh the page and try again.'
        details = {}
    return {'error': {'code': code, 'message': message, 'details': details, 'request_id': request_id}}


class APIResponseMiddleware:
    """Normalize errors after Django has rendered its response, retaining headers/cookies.

    Django converts middleware/view exceptions into responses before this layer
    sees them. Let that path log unexpected exceptions and signal test clients;
    do not convert arbitrary programming errors into client validation failures.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info != '/api/v1' and not request.path_info.startswith('/api/v1/'):
            return self.get_response(request)
        # Never trust or reflect caller-supplied IDs, including on receipt replays.
        request.request_id = 'req_' + uuid.uuid4().hex
        response = self.get_response(request)
        if response.status_code >= 400:
            body = getattr(response, 'data', None)
            if body is None and isinstance(response, JsonResponse):
                body = json.loads(response.content)
            payload = error_body(response.status_code, body, request.request_id)
            if hasattr(response, 'data'):
                response.data = payload
            response.content = json.dumps(payload).encode('utf-8')
            response['Content-Type'] = 'application/json'
            if response.has_header('Content-Length'):
                response['Content-Length'] = str(len(response.content))
            logger.warning('API request %s returned %s', request.request_id, response.status_code)
        response['X-Request-ID'] = request.request_id
        response['Cache-Control'] = 'private, no-store'
        return response


def exception_handler(exc, context):
    """Map known library refusals; leave unexpected failures to Django's 500 path."""
    if isinstance(exc, R.NotFound):
        exc = NotFound()
    elif isinstance(exc, R.Forbidden):
        exc = PermissionDenied()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = PermissionDenied()
    elif isinstance(exc, BU.Invalid):
        exc = ValidationError(str(exc)[:1000])
    elif isinstance(exc, R.RegistryError):
        status = 503 if isinstance(exc, R.Unavailable) else 413 if isinstance(exc, R.TooLarge) else 409
        error = APIException(ERRORS[status][1])
        error.status_code = status
        exc = error
    result = drf_exception_handler(exc, context)
    if result is not None:
        if isinstance(exc, NotAuthenticated):
            result.status_code = 401  # SessionAuthentication otherwise changes this to 403.
        detail = result.data
        if isinstance(detail, dict) and isinstance(detail.get('detail'), str):
            result.data = {'error': {'message': str(detail['detail'])}}
        elif isinstance(detail, list) and len(detail) == 1 and isinstance(detail[0], str):
            result.data = {'error': {'message': str(detail[0])}}
        else:
            result.data = {'error': {'details': detail if isinstance(detail, dict) else {'non_field_errors': detail}}}
    return result


def csrf_failure(request, reason=''):
    # Django's reason can contain origins/configuration; retain it only in its
    # existing server log. DRF's separate session-CSRF path is normalized above.
    return JsonResponse({'error': {'message': 'CSRF verification failed. Refresh the page and try again.'}}, status=403)
