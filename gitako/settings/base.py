"""Base Django settings for Gitako Farm OS."""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CORS_ALLOWED_ORIGINS=(list, []),
)

SECRET_KEY = env("SECRET_KEY", default="insecure-default-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    "django_celery_beat",
    # Local apps
    "apps.tenancy",
    "apps.accounts",
    "apps.farms",
    "apps.enterprises",
    "apps.activities",
    "apps.inventory",
    "apps.finance",
    "apps.sync",
    "apps.notifications",
    "apps.copilot",
    "apps.marketplace",
    "apps.partners",
    "apps.extension",
    "apps.creditscore",
    "apps.payments",
    "apps.finance_partners",
    "apps.ussd",
    "apps.devstore",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.tenancy.middleware.TenantMiddleware",
]

ROOT_URLCONF = "gitako.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.tenancy.admin_context.admin_kpis",
            ],
        },
    },
]

WSGI_APPLICATION = "gitako.wsgi.application"
ASGI_APPLICATION = "gitako.asgi.application"

# Plain PostgreSQL (no PostGIS) so the API runs on standard hosting. The engine
# is pinned regardless of the URL scheme in DATABASE_URL.
DATABASES = {"default": env.db("DATABASE_URL", default="postgres://gitako:gitako_dev@localhost:5432/gitako")}
DATABASES["default"]["ENGINE"] = "django.db.backends.postgresql"

AUTH_USER_MODEL = "accounts.User"
# We enforce uniqueness on phone via a partial constraint (only when set),
# because email-channel users have no phone. The vanilla auth.E003 check
# only knows about full-column uniqueness — silence it.
SILENCED_SYSTEM_CHECKS = ["auth.E003"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-ng"
TIME_ZONE = "Africa/Lagos"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 100,
    # Default rate for the partner API; overridden per-partner at runtime by
    # PartnerRateThrottle from Partner.rate_limit_per_min.
    "DEFAULT_THROTTLE_RATES": {"partner": "60/min"},
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "ALGORITHM": "HS256",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Gitako Farm OS API",
    "DESCRIPTION": "REST API for Gitako Farm OS — Phase 1 (M1–M8).",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

# Email — console in dev, SMTP in prod (set EMAIL_BACKEND + EMAIL_HOST etc.).
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Gitako <no-reply@gitako.farm>")

# Celery
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Gitako-specific
GITAKO = {
    "OTP_LENGTH": 6,
    "OTP_TTL_SECONDS": 5 * 60,
    "OTP_RATE_LIMIT_PER_HOUR": 5,
    "SMS_PROVIDER": env("SMS_PROVIDER", default="console"),
    "TERMII_API_KEY": env("TERMII_API_KEY", default=""),
    "TERMII_SENDER_ID": env("TERMII_SENDER_ID", default="Gitako"),
    # AI co-pilot (M12). "stub" is a deterministic, no-key provider; "claude"
    # uses the Anthropic API and needs ANTHROPIC_API_KEY. Mirrors the SMS seam.
    "LLM_PROVIDER": env("LLM_PROVIDER", default="stub"),
    "ANTHROPIC_API_KEY": env("ANTHROPIC_API_KEY", default=""),
    "ANTHROPIC_MODEL": env("ANTHROPIC_MODEL", default="claude-opus-4-8"),
    # Payments (M17 escrow + M18 disbursement). "stub" moves no real money;
    # "paystack" uses the live API. Mirrors the other provider seams.
    "PAYMENT_PROVIDER": env("PAYMENT_PROVIDER", default="stub"),
    "PAYSTACK_SECRET_KEY": env("PAYSTACK_SECRET_KEY", default=""),
    "S3_ENDPOINT_URL": env("S3_ENDPOINT_URL", default=""),
    "S3_ACCESS_KEY": env("S3_ACCESS_KEY", default=""),
    "S3_SECRET_KEY": env("S3_SECRET_KEY", default=""),
    "S3_BUCKET": env("S3_BUCKET", default="gitako-dev"),
    "S3_REGION": env("S3_REGION", default="fra1"),
}

# Logging — plain stdlib for now. Switch to structlog ProcessorFormatter when
# we wire structlog.configure() in apps/__init__.py.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "console": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "console"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "gitako": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}
