"""Tickster's public Event API v1.0, cached independently of UI filters."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
from threading import Lock
from time import monotonic

import requests
from event_provider_utils import SourceUnavailable, trusted_url, local_utc

API = "https://event.api.tickster.com/api/v1.0/sv/events"
_cache, _lock = OrderedDict(), Lock()


def source_url(value):
    return trusted_url(value, "tickster.com")


def normalize(raw):
    venue = raw.get("venue") or {}
    if ((venue.get("city") or "").strip().casefold() != "stockholm"
            or (venue.get("country") or "").upper() != "SE"
            or raw.get("state") in {"cancelled", "releasedForNonPublicSale"}
            or raw.get("eventHierarchyType") not in {None, "event", "production-child"}):
        return None
    start, end = local_utc(raw.get("startUtc")), local_utc(raw.get("endUtc"))
    url = source_url(raw.get("infoUrl")) or source_url(raw.get("shopUrl"))
    if not start or not url or not raw.get("name"):
        return None
    return {"id": str(raw.get("id") or url), "title": raw["name"], "url": url,
            "image": "", "alt": raw["name"], "credit": "", "category": "Övrigt",
            "venue": venue.get("name") or "", "city": "Stockholm",
            "start": start.date().isoformat(), "end": (end or start).date().isoformat(), "time": start.strftime("%H:%M")}


def _fetch_catalog(key):
    items, total, skip = [], 0, 0
    deadline = monotonic() + 12
    for _ in range(10):
        remaining = deadline - monotonic()
        if remaining <= 0:
            return {"events": items, "truncated": True}
        response = requests.get(API, params={"query": "city:Stockholm", "take": 100, "skip": skip},
                                headers={"X-API-KEY": key}, timeout=(min(3, remaining / 2), min(4, remaining / 2)), allow_redirects=False)
        if response.status_code != 200 or len(response.content) > 8_000_000:
            raise SourceUnavailable()
        raw = response.json()
        total = int(raw["totalItems"])
        batch = raw.get("items") or []
        for entry in batch:
            event = normalize(entry)
            if event:
                items.append(event)
        if skip + len(batch) >= total:
            return {"events": items, "truncated": False}
        if not batch:
            raise SourceUnavailable()
        skip += len(batch)
    return {"events": items, "truncated": total > skip}


def get_catalog(key, start_date="", end_date=""):
    if not key:
        raise SourceUnavailable()
    identity = sha256(key.encode()).hexdigest()
    with _lock:
        cached = _cache.get(identity)
        stale = False
        if cached and monotonic() - cached[0] < 3600:
            data = cached[1]
        else:
            try:
                data = _fetch_catalog(key)
            except (requests.RequestException, SourceUnavailable, ValueError, KeyError, TypeError, AttributeError):
                if not cached or monotonic() - cached[0] >= 7200:
                    raise SourceUnavailable() from None
                data, stale = cached[1], True
            else:
                _cache[identity] = (monotonic(), data)
                while len(_cache) > 4:
                    _cache.popitem(last=False)
        return deepcopy({**data, "events": [e for e in data["events"]
                         if (not start_date or e["end"] >= start_date) and (not end_date or e["start"] <= end_date)], "stale": stale})
