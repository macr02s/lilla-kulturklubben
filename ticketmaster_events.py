"""Server-side Ticketmaster Discovery adapter, restricted to Stockholm venues."""
from collections import OrderedDict
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit, urlunsplit

import requests

API = "https://app.ticketmaster.com/discovery/v2/events.json"
TTL, STALE_TTL, PAGE_SIZE = 600, 3600, 200
_cache, _lock = OrderedDict(), Lock()
LABELS = {"Music": "Musik", "Arts & Theatre": "Scenkonst", "Sports": "Sport",
          "Film": "Film", "Miscellaneous": "Övrigt"}


class SourceUnavailable(Exception):
    pass


def source_url(value, image=False):
    if not isinstance(value, str):
        return ""
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        domains = ("ticketmaster.se", "ticketmaster.com")
        if image:
            domains += ("ticketm.net", "ticketmaster.eu", "tmol.io")
        trusted = any(host == domain or host.endswith("." + domain) for domain in domains)
        if not trusted or parts.scheme not in {"http", "https"} or parts.username or parts.password or parts.port not in {None, 80, 443}:
            return ""
        return urlunsplit(("https", host, parts.path, parts.query, ""))
    except ValueError:
        return ""


def _fetch(api_key, page, start_date="", end_date=""):
    params = {
        "apikey": api_key, "countryCode": "SE", "city": "Stockholm",
        "locale": "sv-se,sv,en,*",
        "sort": "date,asc", "size": PAGE_SIZE, "page": page,
        "startDateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if start_date:
        params.pop("startDateTime")
        params["localStartDateTime"] = start_date + "T00:00:00," + end_date + "T23:59:59"
    response = requests.get(API, params=params, timeout=(5, 15), allow_redirects=False)
    if response.status_code != 200 or len(response.content) > 8_000_000:
        raise SourceUnavailable()
    return response.json()


def _event(raw):
    venue = next((v for v in (raw.get("_embedded") or {}).get("venues", [])
                  if (v.get("city") or {}).get("name", "").strip().casefold() == "stockholm"
                  and (v.get("country") or {}).get("countryCode") == "SE"), None)
    url = source_url(raw.get("url"))
    if not venue or not url or not raw.get("name") or not raw.get("id"):
        return None
    classification = next(iter(raw.get("classifications") or []), {})
    segment, genre = classification.get("segment") or {}, classification.get("genre") or {}
    start = (raw.get("dates") or {}).get("start") or {}
    local_date = start.get("localDate")
    if local_date:
        date.fromisoformat(local_date)
    images = [i for i in raw.get("images", []) if source_url(i.get("url"), image=True)]
    images.sort(key=lambda i: (i.get("ratio") != "16_9", abs((i.get("width") or 0) - 640)))
    return {"id": raw["id"], "title": raw["name"], "url": url,
            "image": source_url(images[0]["url"], image=True) if images else "",
            "alt": raw["name"], "credit": "", "venue": venue.get("name") or "",
            "city": "Stockholm", "start": local_date, "end": None,
            "time": "" if start.get("timeTBA") or start.get("noSpecificTime") else (start.get("localTime") or "")[:5],
            "category": LABELS.get(segment.get("name"), segment.get("name") or "Övrigt"),
            "category_id": str(segment.get("id") or "other").casefold(),
            "genre": genre.get("name") or "", "genre_id": str(genre.get("id") or "").casefold()}


def _catalog(api_key, start_date="", end_date=""):
    items, seen, total_pages = [], set(), 1
    for page in range(5):
        raw = _fetch(api_key, page, start_date, end_date) if start_date else _fetch(api_key, page)
        total_pages = int(raw["page"]["totalPages"])
        for entry in (raw.get("_embedded") or {}).get("events", []):
            event = _event(entry)
            if start_date and event and (not event["start"] or not start_date <= event["start"] <= end_date):
                continue
            if event and event["id"] not in seen:
                seen.add(event["id"])
                items.append(event)
        if page + 1 >= total_pages:
            break
    categories = {}
    for event in items:
        category = categories.setdefault(event["category_id"], {
            "slug": event["category_id"], "title": event["category"], "children": {}})
        if event["genre_id"] and event["genre"] not in {"", "Undefined"}:
            category["children"][event["genre_id"]] = event["genre"]
    return {"events": items, "categories": [
        {"slug": c["slug"], "title": c["title"], "subcategories": [
            {"slug": slug, "title": title} for slug, title in sorted(c["children"].items(), key=lambda pair: pair[1])]}
        for c in sorted(categories.values(), key=lambda c: c["title"])],
        "truncated": total_pages > 5, "updated": datetime.now(timezone.utc).isoformat()}


def get_events(api_key, category="", subcategory="", page=1, start_date="", end_date="", page_size=9):
    if not api_key:
        raise SourceUnavailable()
    key = sha256(api_key.encode()).hexdigest()
    if start_date:
        key = (key, start_date, end_date)
    stale = False
    with _lock:
        cached = _cache.get(key)
        if cached and monotonic() - cached[0] < TTL:
            catalog = cached[1]
        else:
            try:
                catalog = _catalog(api_key, start_date, end_date) if start_date else _catalog(api_key)
            except (requests.RequestException, SourceUnavailable, ValueError, KeyError, TypeError, AttributeError):
                if not cached or monotonic() - cached[0] >= STALE_TTL:
                    raise SourceUnavailable() from None
                catalog, stale = cached[1], True
            else:
                _cache[key] = (monotonic(), catalog)
                _cache.move_to_end(key)
                while len(_cache) > 4:
                    _cache.popitem(last=False)
        items = [e for e in catalog["events"] if (not category or e["category_id"] == category)
                 and (not subcategory or e["genre_id"] == subcategory)]
        offset = (page - 1) * page_size
        return deepcopy({"events": items[offset:offset + page_size], "categories": catalog["categories"],
                         "count": len(items), "page": page, "next": page + 1 if offset + page_size < len(items) else None,
                         "stale": stale, "truncated": catalog["truncated"], "updated": catalog["updated"]})
