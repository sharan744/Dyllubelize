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
SECRET_KEY = "BkNaS43up1TbE3pJpgcctWMNuBHXpj4oc1gAA73M5C-V7HQKrRK7_sxznHG8cySFmvY"

DEBUG = True

ALLOWED_HOSTS = [
    "139.59.6.61",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
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
]

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
        'NAME': 'dyllubelize',
        'USER': 'dyllubelize',
        'PASSWORD': 'Dyllu@2026#Secure',
        'HOST': '139.59.6.61',
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
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "ghai quwx mxql cjms")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "UDL Belize <sharanic44@gmail.com>")

if USE_CONSOLE_EMAIL:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
