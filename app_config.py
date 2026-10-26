"""Environment-driven settings for local development, Render and custom domains."""
from datetime import timedelta
from urllib.parse import urlsplit

from dotenv import dotenv_values


def on_render(environ):
    return environ.get("RENDER", "").lower() == "true" or bool(environ.get("RENDER_EXTERNAL_URL", "").strip())


def runtime_environment(environ, env_file):
    """Use .env on the developer's computer; Render uses service variables only."""
    if on_render(environ):
        return dict(environ)
    local = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
    return {**local, **environ}


def _loopback_http(value):
    parts = urlsplit(value)
    return parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost", "::1"}


def auth_settings(environ):
    # Never derive OAuth callback URLs from an incoming Host header.
    hosted = on_render(environ)
    public_url = environ.get("PUBLIC_BASE_URL", "").strip()
    if hosted and _loopback_http(public_url):
        public_url = ""
    base_url = (public_url or environ.get("RENDER_EXTERNAL_URL", "").strip()
                or "http://127.0.0.1:5000").rstrip("/")
    redirect_uri = (environ.get("GOOGLE_REDIRECT_URI") or "").strip()
    # A local .env imported into Render must not send members to their own computer.
    if hosted and _loopback_http(redirect_uri):
        redirect_uri = ""
    if not redirect_uri:
        parts = urlsplit(base_url)
        local = parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost"}
        if (not parts.hostname or (parts.scheme != "https" and not local)
                or parts.path or parts.query or parts.fragment or parts.username):
            raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin, or localhost over HTTP.")
        redirect_uri = base_url + "/auth/google/callback"
    local_http = not hosted and _loopback_http(redirect_uri)
    bank_callback_path = environ.get("ENABLE_BANKING_CALLBACK_PATH", "/bank/callback").strip() or "/bank/callback"
    if bank_callback_path not in {"/bank/callback", "/callback"}:
        raise ValueError("ENABLE_BANKING_CALLBACK_PATH must be /bank/callback or /callback.")
    settings = {
        "SECRET_KEY": environ.get("SECRET_KEY"),
        "GOOGLE_CLIENT_ID": environ.get("GOOGLE_CLIENT_ID", ""),
        "GOOGLE_CLIENT_SECRET": environ.get("GOOGLE_CLIENT_SECRET", ""),
        "GOOGLE_REDIRECT_URI": redirect_uri,
        "CLUB_MEMBERS": environ.get("CLUB_MEMBERS", ""),
        "CLUB_CALENDAR_ID": environ.get("CLUB_CALENDAR_ID", "").strip(),
        "ENABLE_BANKING_APPLICATION_ID": environ.get("ENABLE_BANKING_APPLICATION_ID", "").strip(),
        "ENABLE_BANKING_PRIVATE_KEY_PATH": environ.get("ENABLE_BANKING_PRIVATE_KEY_PATH", "").strip(),
        "ENABLE_BANKING_ADMIN_EMAIL": environ.get("ENABLE_BANKING_ADMIN_EMAIL", "").strip().casefold(),
        "ENABLE_BANKING_ENCRYPTION_KEY": environ.get("ENABLE_BANKING_ENCRYPTION_KEY", "").strip(),
        "ENABLE_BANKING_ENVIRONMENT": environ.get("ENABLE_BANKING_ENVIRONMENT", "SANDBOX").strip().upper() or "SANDBOX",
        "ENABLE_BANKING_REDIRECT_URI": redirect_uri.rsplit("/auth/google/callback", 1)[0] + bank_callback_path,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": not local_http or environ.get("SESSION_COOKIE_SECURE", "").lower() == "true",
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
        "SESSION_REFRESH_EACH_REQUEST": False,
    }
    if environ.get("CLUB_DATABASE", "").strip():
        settings["CLUB_DATABASE"] = environ["CLUB_DATABASE"].strip()
    return settings
