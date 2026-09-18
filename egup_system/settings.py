import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------
# This is the ONLY settings file. There used to be a separate
# settings_production.py (Railway-specific) left over from Project A —
# it referenced apps that no longer exist (`membership`/`payments` were
# retired during the migration) and would have crashed on startup if
# ever actually deployed. It has been deleted. Local dev and production
# both use THIS file; behaviour switches on environment variables only,
# per Django's own recommended pattern (twelve-factor config).
# ---------------------------------------------------------------------

# SECURITY: DEBUG now defaults to False, not True. A missing DEBUG
# variable in production used to silently mean "run with full stack
# traces, settings, and SQL queries visible to any visitor who triggers
# an error" — exactly backwards. Local dev now needs `DEBUG=True` set
# explicitly (one line in your local .env) — a small one-time cost in
# exchange for production never failing open by accident.
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

# SECURITY: fails hard instead of silently using a known, source-visible
# fallback key. The previous version of this comment claimed "an app
# that boots with an obviously-fake dev key is a safer failure mode than
# one that silently uses a secret sitting in source control" — but that
# is exactly backwards: a fake key that still lets the app boot and serve
# traffic normally provides no warning signal at all if it ends up in
# production. A key visible in this file is not a secret regardless of
# whether DEBUG is on, since anyone with source access already has it —
# so the actual fallback below is intentionally still only for DEBUG=True
# (single-process local dev has no attacker with network access to begin
# with), and production (DEBUG=False) is required to set a real one or
# the app refuses to start.
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-DEV-ONLY-DO-NOT-DEPLOY-set-SECRET_KEY-env-var'
    else:
        raise ImproperlyConfigured(
            "SECRET_KEY environment variable is required when DEBUG=False. "
            "Refusing to start with an insecure fallback key in production."
        )

# Comma-separated in production, e.g. "egup.example.com,www.egup.example.com".
# Falls back to localhost/127.0.0.1 automatically when DEBUG is on and
# nothing was set, so local testing needs no ALLOWED_HOSTS configuration.
_allowed_hosts_env = os.environ.get('ALLOWED_HOSTS', '')
ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_env.split(',') if h.strip()]
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']

# Cloudflare sits in front of Django in production. Only trust
# X-Forwarded-Proto for HTTPS detection when something in front of Django
# is guaranteed to set/strip it correctly (Cloudflare, or nginx configured
# to clear any client-supplied copy first) — see DEPLOYMENT.md. Harmless
# locally since local requests are plain HTTP without this header anyway.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
# Defense-in-depth alongside Cloudflare's own HTTPS enforcement — redirects
# any request Django sees as plain HTTP. Off in DEBUG so local http://
# development still works without a certificate.
SECURE_SSL_REDIRECT = not DEBUG

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',
    'axes',          # brute-force protection
    'apps.accounts',
    'apps.audit',
    'apps.members',
    'apps.memberships',
    'apps.payments',
    'apps.content',
    'apps.media_lib',
    'apps.events',
    'apps.announcements',
    'apps.monitoring',
    # (Legacy Project A reference directories apps/members_legacy_ref and
    # apps/payments_legacy_ref were kept temporarily during migration and
    # have now been deleted — everything useful from them was already
    # ported: the membership-number counter into apps.members, the
    # security middleware/rate-limiting into apps.monitoring.)
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # serves static files in production — must be right after SecurityMiddleware
    'apps.monitoring.middleware.SecurityHeadersMiddleware',   # security headers
    'apps.monitoring.middleware.IPBlockMiddleware',            # IP blocklist
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'axes.middleware.AxesMiddleware',                    # axes must be after auth
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'egup_system.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.accounts.context_processors.admin_profile',
                'apps.accounts.context_processors.active_nav',
                'apps.accounts.context_processors.topbar_alerts',
            ],
        },
    },
]

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',   # axes backend first
    'django.contrib.auth.backends.ModelBackend',
]

DATABASES = {
    'default': dj_database_url.config(
        # No DATABASE_URL set → local SQLite file, zero config needed for
        # local testing. Set DATABASE_URL (e.g.
        # postgres://user:pass@localhost:5432/egup) to test against a
        # real Postgres locally, or in production — same variable, same
        # code path either way, per the brief's requirement that
        # PostgreSQL be the production database while still allowing
        # SQLite for local dev when intentionally chosen.
        default=f"sqlite:///{BASE_DIR / 'egup.db'}",
        conn_max_age=600,
    )
}

# ─── CACHE / RATE LIMITING ──────────────────────────────────────────────────
# apps/payments/rate_limit.py (payment attempts, manual-submission cooldowns)
# and django-axes (login lockouts) both go through Django's cache framework.
# Without this, Django silently falls back to LocMemCache — an in-memory
# dict PER WORKER PROCESS. On a production gunicorn deployment with more
# than one worker, that means an attacker can bypass every rate limit in
# this app just by spreading requests across workers; each one has its own
# independent counter that knows nothing about the others.
#
# Set REDIS_URL in production (e.g. `redis://user:pass@host:6379/0`) — most
# hosts (Railway, Render, Heroku) provision this as a one-click add-on.
# Falls back to LocMemCache only when REDIS_URL is unset, which is fine for
# local single-process development but MUST NOT be relied on in production.
REDIS_URL = os.environ.get('REDIS_URL', '')
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

# See apps/members/sms.py — no SMS gateway is wired in yet. This stays
# False (OTPs log to server logs instead of sending) until a real
# provider is implemented there and this is explicitly set True/via env.
SMS_PROVIDER_CONFIGURED = os.environ.get('SMS_PROVIDER_CONFIGURED', 'False') == 'True'

# ─── DJANGO-AXES SETTINGS ──────────────────────────────────────────────────
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5           # lock after 5 failed attempts
AXES_COOLOFF_TIME = 0.5          # lockout for 30 minutes (in hours)
AXES_LOCKOUT_CALLABLE = None
AXES_RESET_ON_SUCCESS = True     # reset counter on successful login
AXES_LOCKOUT_PARAMETERS = ['ip_address', 'username']   # lock per IP+username
AXES_NEVER_LOCKOUT_WHITELIST = False
AXES_IP_WHITELIST = []
AXES_HTTP_RESPONSE_CODE = 403
AXES_VERBOSE = False
AXES_HANDLER = 'axes.handlers.database.AxesDatabaseHandler'

# ─── SESSION SECURITY ──────────────────────────────────────────────────────
SESSION_COOKIE_HTTPONLY = True       # JS cannot access session cookie
SESSION_COOKIE_SAMESITE = 'Lax'     # CSRF protection
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 28800           # 8 hours session timeout
CSRF_TRUSTED_ORIGINS = [h.strip() for h in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if h.strip()]
# This MUST be False, not True. Every fetch()-based POST on the public
# site (registration, renewal, contact, manual payment submission — see
# static/js/django-client.js's getCookie("csrftoken")) works by reading
# this cookie in JavaScript and sending it back as the X-CSRFToken
# header — that is Django's own documented pattern for AJAX CSRF
# protection. With HTTPONLY True, JS can't read the cookie at all,
# every one of those requests sends a blank/invalid token, and Django's
# CSRF middleware rejects them with its own 403 HTML page *before the
# view ever runs* — which is why it looked like "something went wrong"
# with no detail and no trace in the logs: the request never reached
# the code that would have explained it. The *session* cookie right
# above this should stay HttpOnly (JS never needs to read that one) —
# only the CSRF cookie needs to be readable, by design.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'

# Secure by default whenever DEBUG is off (production); allowed to be
# plain HTTP locally so `runserver` works without HTTPS. An explicit
# COOKIE_SECURE env var can force either way if a deployment needs it
# (e.g. testing production settings locally over HTTP intentionally).
_cookie_secure_env = os.environ.get('COOKIE_SECURE')
if _cookie_secure_env is not None:
    _cookie_secure = _cookie_secure_env == 'True'
else:
    _cookie_secure = not DEBUG
SESSION_COOKIE_SECURE = _cookie_secure
CSRF_COOKIE_SECURE = _cookie_secure

# ─── PASSWORD VALIDATION ───────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Object storage (brief section 21): local filesystem by default (dev
# only — fine for a single-server setup, but not durable/scalable and
# wrong for anything with multiple app instances). Set USE_S3_STORAGE=True
# with the AWS_* variables below to switch to S3-compatible storage
# (works with AWS S3 itself, or any S3-compatible provider via
# AWS_S3_ENDPOINT_URL, e.g. Backblaze B2, DigitalOcean Spaces, Cloudflare R2).
USE_S3_STORAGE = os.environ.get('USE_S3_STORAGE', 'False') == 'True'
if USE_S3_STORAGE:
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
    AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL') or None  # None = real AWS S3
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', '')
    AWS_DEFAULT_ACL = None  # bucket policy controls access, not per-object ACLs
    AWS_QUERYSTRING_AUTH = False  # public bucket/CDN in front — no signed URLs needed
    AWS_S3_FILE_OVERWRITE = False  # never let django-storages silently overwrite same-named uploads
else:
    # Local filesystem media (fine for a single-server deploy; switch to
    # USE_S3_STORAGE for anything with multiple app instances). Static
    # files always go through WhiteNoise's compressed+hashed storage
    # regardless of media backend — this is what actually serves CSS/JS/
    # images in production without a separate nginx/CDN static config.
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

_admin_prefix = os.environ.get('ADMIN_ROUTE_PREFIX', '/dashboard/')
LOGIN_URL = f'{_admin_prefix}login/'
LOGIN_REDIRECT_URL = f'{_admin_prefix}'
LOGOUT_REDIRECT_URL = f'{_admin_prefix}login/'

REGISTRATION_FEE = 200  # fallback only; SystemSettings.registration_fee (DB, admin-editable) takes priority
RENEWAL_FEE = 100  # fallback only; SystemSettings.renewal_fee (DB, admin-editable) takes priority
MEMBERSHIP_VALIDITY_YEARS = 1

# PayHero — PRIMARY payment provider (apps/payments/providers.py). Never
# expose these to any frontend/browser context; server-side only. These
# env vars are the FALLBACK — an admin can also set/rotate credentials
# from the dashboard (Finance > Payment Credentials), stored encrypted
# in the DB via FIELD_ENCRYPTION_KEY below, which takes priority when set.
PAYHERO_API_USERNAME = os.environ.get('PAYHERO_API_USERNAME', '')
PAYHERO_API_PASSWORD = os.environ.get('PAYHERO_API_PASSWORD', '')
PAYHERO_CHANNEL_ID = os.environ.get('PAYHERO_CHANNEL_ID', '')
PAYHERO_CALLBACK_BASE_URL = os.environ.get('PAYHERO_CALLBACK_BASE_URL', '')

# Key for encrypting DB-stored payment credentials (apps/payments/crypto.py).
# Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Required only if you plan to set credentials via the admin dashboard
# rather than environment variables alone. Treat it exactly like
# SECRET_KEY — never commit it, never reuse it across environments.
FIELD_ENCRYPTION_KEY = os.environ.get('FIELD_ENCRYPTION_KEY', '')

# Daraja — SECONDARY/fallback, not yet audited to the same standard as
# PayHero (see apps/payments/providers.py:DarajaProvider docstring).
MPESA_ENVIRONMENT = os.environ.get('MPESA_ENVIRONMENT', 'sandbox')
MPESA_CONSUMER_KEY = os.environ.get('MPESA_CONSUMER_KEY', '')
MPESA_CONSUMER_SECRET = os.environ.get('MPESA_CONSUMER_SECRET', '')
MPESA_PASSKEY = os.environ.get('MPESA_PASSKEY', '')
MPESA_SHORTCODE = os.environ.get('MPESA_SHORTCODE', '')

# True in every real deployment (Cloudflare is always in front per the
# target architecture). Only set False for local dev without Cloudflare,
# so apps.monitoring.ip_utils falls back to X-Forwarded-For/REMOTE_ADDR.
# Default: on in production, off for local testing (no Cloudflare in
# front of `runserver`) — matches DEBUG unless explicitly overridden.
BEHIND_CLOUDFLARE = os.environ.get('BEHIND_CLOUDFLARE', 'False' if DEBUG else 'True') == 'True'

# Discreet (not secret-by-obscurity-alone — see brief section 22) admin
# route prefix. Change the default before deploying; real protection is
# still authentication + RBAC + rate limiting, this just avoids
# advertising the path in public navigation/robots.
ADMIN_ROUTE_PREFIX = os.environ.get('ADMIN_ROUTE_PREFIX', '/dashboard/')


# ─── LOGGING ───────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'egup': {
            'format': '[{asctime}] [{levelname}] {name}: {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'egup',
        },
        'security_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'security.log',
            'maxBytes': 5 * 1024 * 1024,  # 5MB
            'backupCount': 3,
            'formatter': 'egup',
        },
    },
    'loggers': {
        'egup.security': {
            'handlers': ['console', 'security_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'axes': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        # Every app.* logger (apps.members.api's log_unhandled_errors,
        # etc.) — without this, an unhandled exception in a view has
        # nowhere defined to go and silently vanishes except for
        # whatever Python's own last-resort stderr fallback catches.
        'apps': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
