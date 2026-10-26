"""Small helpers for the Tickster and Kulturbiljetter read-only adapters."""
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo


class SourceUnavailable(Exception):
    pass


def trusted_url(value, domain):
    if not isinstance(value, str):
        return ""
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        if (parts.scheme in {"http", "https"} and (host == domain or host.endswith("." + domain))
                and not parts.username and not parts.password and parts.port in {None, 80, 443}):
            return urlunsplit(("https", host, parts.path, parts.query, ""))
    except ValueError:
        pass
    return ""


def local_utc(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo("Europe/Stockholm"))
    except ValueError:
        return None


def collection(value):
    if value is None:
        return []
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return value
    raise SourceUnavailable()
