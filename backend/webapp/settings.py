# SPDX-License-Identifier: AGPL-3.0-only
"""PostgreSQL web application; engine workers remain separate."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

ROOT = Path(__file__).resolve().parents[2]
DEBUG = os.environ.get('BIO_WEB_DEBUG') == '1'
SECRET_KEY = os.environ.get('BIO_WEB_SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured('Set BIO_WEB_SECRET_KEY to a private random value')
ALLOWED_HOSTS = os.environ.get('BIO_WEB_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
ROOT_URLCONF = 'backend.webapp.urls'
WSGI_APPLICATION = 'backend.webapp.wsgi.application'
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
                  'rest_framework', 'backend.webapp']
MIDDLEWARE = ['backend.webapp.api_errors.APIResponseMiddleware',
              'django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
              'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
              'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql',
    'NAME': os.environ.get('BIO_PGDATABASE', 'battle_it_out'), 'USER': os.environ.get('BIO_PGUSER', 'bio'),
    'PASSWORD': os.environ.get('BIO_PGPASSWORD', ''), 'HOST': os.environ.get('BIO_PGHOST', '127.0.0.1'),
    'PORT': os.environ.get('BIO_PGPORT', '5432'), 'CONN_MAX_AGE': 0}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
TIME_ZONE = 'UTC'
BIO_DATA_DIR = Path(os.environ.get('BIO_DATA_DIR', ROOT / 'backend/webapp/.state'))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_FAILURE_VIEW = 'backend.webapp.api_errors.csrf_failure'
CSRF_TRUSTED_ORIGINS = os.environ.get('BIO_WEB_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(',') if DEBUG else os.environ.get('BIO_WEB_ORIGINS', '').split(',') if os.environ.get('BIO_WEB_ORIGINS') else []
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 512 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024
REST_FRAMEWORK = {'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
                  'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
                  'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
                  'EXCEPTION_HANDLER': 'backend.webapp.api_errors.exception_handler'}
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
