"""Billetto's authenticated public publisher API; never the organiser API."""
from datetime import datetime
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests
from billetto_images import image_url

API = "https://billetto.se/api/v3/public/events"


class SourceUnavailable(Exception):
    pass


def event_url(value):
    try:
        parts = urlsplit(value or "")
        if (parts.scheme == "https" and parts.hostname in {"billetto.se", "www.billetto.se"}
                and not parts.username and not parts.password and parts.port in {None, 443}):
            return value  # Required UTM parameters must remain intact.
    except ValueError:
        pass
    return ""


def _local(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Event timestamp lacks timezone")
    return parsed.astimezone(ZoneInfo("Europe/Stockholm"))


def normalize(raw):
    location = raw.get("location") or {}
    if (raw.get("state") != "published" or (location.get("city") or "").strip().casefold() != "stockholm"
            or (location.get("country_code") or "").upper() != "SE"):
        return None
    url, start, end = event_url(raw.get("url")), _local(raw.get("startdate")), _local(raw.get("enddate"))
    if not url or not start or not raw.get("title"):
        return None
    categorisation = raw.get("categorization") or raw.get("categorisation") or {}
    category = categorisation.get("category_localized") or categorisation.get("category") or ""
    if isinstance(category, dict):
        category = category.get("name") or ""
    return {"id": str(raw.get("id") or url), "title": raw["title"], "url": url,
            "image": image_url(raw.get("image_link")), "alt": raw["title"], "credit": "",
            "category": category or "Övrigt", "venue": location.get("location_name") or location.get("name") or "",
            "genre": categorisation.get("subcategory_localized") or categorisation.get("subcategory") or "",
            "city": "Stockholm", "start": start.date().isoformat(),
            "end": (end or start).date().isoformat(), "time": start.strftime("%H:%M")}


def get_catalog(keypair, start_date="", end_date=""):
    if not keypair or ":" not in keypair or any(not part.strip() for part in keypair.split(":", 1)):
        raise SourceUnavailable()
    base_params = {"limit": 100, "region": "Stockholm"}
    url, params = API, dict(base_params)
    items, visited = [], set()
    try:
        for page in range(10):
            request_key = (url, tuple(sorted((params or {}).items())))
            if request_key in visited:
                raise SourceUnavailable()
            visited.add(request_key)
            response = requests.get(url, params=params, headers={"Api-Keypair": keypair},
                                    timeout=(5, 15), allow_redirects=False)
            if response.status_code != 200 or len(response.content) > 8_000_000:
                raise SourceUnavailable()
            raw = response.json()
            for entry in raw["data"]:
                event = normalize(entry)
                if event and (not start_date or event["end"] >= start_date) and (not end_date or event["start"] <= end_date):
                    items.append(event)
            pagination = raw.get("pagination") or raw
            if not pagination.get("has_more"):
                return {"events": items, "truncated": False}
            if not pagination.get("next_url"):
                # The live public API returns a list with has_more and an `after` ID cursor.
                entries = raw["data"]
                last_id = str(entries[-1].get("id") or "") if entries else ""
                if not last_id or len(last_id) > 200:
                    raise SourceUnavailable()
                url, params = API, {**base_params, "after": last_id}
                continue
            next_url = urljoin(API, pagination.get("next_url") or "")
            parts = urlsplit(next_url)
            # Never forward credentials to a next-page host supplied by an API response.
            if (parts.scheme != "https" or parts.netloc != "billetto.se" or parts.path != "/api/v3/public/events"
                    or parts.username or parts.password or not pagination.get("next_url")):
                raise SourceUnavailable()
            url, params = next_url, None
        return {"events": items, "truncated": True}
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        raise SourceUnavailable() from None
