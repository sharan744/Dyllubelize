"""
Django settings for Flujo — Sales, Order Processing & Dispatch Management.

Designed to run entirely on a local machine (no external server required).
Configuration is read from a .env file so the client can change database
credentials and company details without touching the code.
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Minimal .env loader (no external dependency required)
# ---------------------------------------------------------------------------
def _load_env(path: Path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return env(key, str(default)).lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY", "BkNaS43up1TbE3pJpgcctWMNuBHXpj4oc1gAA73M5C-V7HQKrRK7_sxznHG8cySFmvY")
DEBUG = False

ALLOWED_HOSTS = [
    '64.227.167.71',
    'localhost',
    '127.0.0.1',
]

# Needed in production (DEBUG=False behind HTTPS): the domains allowed to POST
# forms, and telling Django it is served over HTTPS by the Nginx proxy.
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Third-party
    "rest_framework",
    "rest_framework.authtoken",
    # Local apps
    "accounts",
    "catalogue",
    "orders",
    "dispatchapp",
    "delivery",
    "returnsapp",
    "inventory",
    "accounting",
    "core",
    "api",
]

# Django REST Framework — token auth for the Flutter mobile app
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.company_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Database — PostgreSQL
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'dyllu_db',
        'USER': 'dyllu_user',
        'PASSWORD': 'dyllu@26',
        'HOST': '127.0.0.1',
        'PORT': '5432',
    }
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 6}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# I18N / L10N — defaults suited to a Mexico-based client
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "America/Belize")
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# Business defaults (also editable in the admin via SiteSetting)
CURRENCY_SYMBOL = env("CURRENCY_SYMBOL", "$")
CURRENCY_CODE = env("CURRENCY_CODE", "BZD")

# ---------------------------------------------------------------------------
# Email / notifications  (Gmail SMTP, configured here in settings)
#
#   >>> Paste your Gmail APP PASSWORD into EMAIL_HOST_PASSWORD below. <<<
#   It must be a 16-character Gmail *App Password* (Google Account >
#   Security > 2-Step Verification > App passwords), NOT your normal
#   Gmail login password.
#
# While the password is left as the placeholder, real sending will simply
# fail quietly (notifications are best-effort). Set USE_CONSOLE_EMAIL = True
# to print emails to the terminal instead of sending them.
# ---------------------------------------------------------------------------
NOTIFY_ENABLED = env_bool("NOTIFY_ENABLED", True)
USE_CONSOLE_EMAIL = env_bool("USE_CONSOLE_EMAIL", False)

EMAIL_HOST = env("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "sharanic44@gmail.com")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "PASTE_YOUR_16_CHAR_APP_PASSWORD_HERE")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "UDL Belize <sharanic44@gmail.com>")

if USE_CONSOLE_EMAIL:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
