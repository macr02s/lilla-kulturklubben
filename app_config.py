"""Environment-driven settings for local development, Render and custom domains."""
from datetime import timedelta
from urllib.parse import urlsplit


def auth_settings(environ):
    # Never derive OAuth callback URLs from an incoming Host header.
    base_url = (environ.get("PUBLIC_BASE_URL") or environ.get("RENDER_EXTERNAL_URL")
                or "http://127.0.0.1:5000").strip().rstrip("/")
    redirect_uri = (environ.get("GOOGLE_REDIRECT_URI") or "").strip()
    if not redirect_uri:
        parts = urlsplit(base_url)
        local = parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost"}
        if (not parts.hostname or (parts.scheme != "https" and not local)
                or parts.path or parts.query or parts.fragment or parts.username):
            raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin, or localhost over HTTP.")
        redirect_uri = base_url + "/auth/google/callback"
    callback = urlsplit(redirect_uri)
    local_http = callback.scheme == "http" and callback.hostname in {"127.0.0.1", "localhost"}
    settings = {
        "SECRET_KEY": environ.get("SECRET_KEY"),
        "GOOGLE_CLIENT_ID": environ.get("GOOGLE_CLIENT_ID", ""),
        "GOOGLE_CLIENT_SECRET": environ.get("GOOGLE_CLIENT_SECRET", ""),
        "GOOGLE_REDIRECT_URI": redirect_uri,
        "CLUB_MEMBERS": environ.get("CLUB_MEMBERS", ""),
        "CLUB_CALENDAR_ID": environ.get("CLUB_CALENDAR_ID", "").strip(),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": environ.get("SESSION_COOKIE_SECURE", "false" if local_http else "true").lower() == "true",
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
        "SESSION_REFRESH_EACH_REQUEST": False,
    }
    if environ.get("CLUB_DATABASE", "").strip():
        settings["CLUB_DATABASE"] = environ["CLUB_DATABASE"].strip()
    return settings
