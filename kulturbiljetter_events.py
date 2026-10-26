"""Kulturbiljetter Events API v3 with ETag reuse and bounded detail loading."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timezone
from hashlib import sha256
import re
from threading import Lock
from time import monotonic
from zoneinfo import ZoneInfo

import requests
from event_provider_utils import SourceUnavailable, trusted_url, collection

API = "https://kulturbiljetter.se/api/v3/events/"
_lock = Lock()
_indexes, _details, _attempts = OrderedDict(), OrderedDict(), OrderedDict()
_inflight = set()


def source_url(value):
    return trusted_url(value, "kulturbiljetter.se")


def normalize(raw, event_id):
    url = source_url(raw.get("url_event_page"))
    if not url or not raw.get("title"):
        return []
    locations = {str(place["location_id"]): place for place in collection(raw.get("locations"))}
    images = [source_url(value) for value in collection(raw.get("images"))]
    image = next((value for value in images if value), "")
    events = []
    for occurrence in collection(raw.get("dates")):
        place = locations.get(str(occurrence.get("location_id")), {})
        if (place.get("city") or "").strip().casefold() != "stockholm":
            continue
        try:
            timestamp = occurrence.get("unixtime_start")
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                continue
            start = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(ZoneInfo("Europe/Stockholm"))
        except (ValueError, OverflowError, OSError):
            continue
        events.append({"id": str(event_id) + ":" + str(occurrence.get("date_id") or timestamp),
                       "title": raw["title"], "url": url, "image": image, "alt": raw["title"], "credit": "",
                       "category": "Övrigt", "venue": place.get("name") or "", "city": "Stockholm",
                       "start": start.date().isoformat(), "end": start.date().isoformat(),
                       "time": "" if occurrence.get("date_only") else start.strftime("%H:%M")})
    return events


def _request(key, path="", etag=""):
    headers = {"Authorization": "Token " + key}
    if etag:
        headers["If-None-Match"] = '"' + etag + '"'
    response = requests.get(API + path, headers=headers, timeout=(3, 4), allow_redirects=False)
    if response.status_code not in {200, 304} or len(response.content) > 8_000_000:
        raise SourceUnavailable()
    return response


def _index(key, identity):
    with _lock:
        saved = _indexes.get(identity)
        if saved and monotonic() - saved[0] < 600:
            return saved[1]
    response = _request(key)
    if response.status_code != 200:
        raise SourceUnavailable()
    entries = []
    for entry in collection(response.json()):
        identifier = str(entry.get("event_id") or "")
        if not re.fullmatch(r"[0-9]{1,18}", identifier) or int(identifier) <= 0:
            continue
        etag = str(entry.get("ETag") or "").strip('"')
        if len(etag) > 200 or "\r" in etag or "\n" in etag:
            raise SourceUnavailable()
        entries.append((identifier, etag))
    entries = list(dict.fromkeys(entries))
    with _lock:
        _indexes[identity] = (monotonic(), entries)
        while len(_indexes) > 4:
            _indexes.popitem(last=False)
    return entries


def _load_detail(key, identity, identifier, wanted_etag):
    cache_key = (identity, identifier)
    try:
        with _lock:
            previous = _details.get(cache_key)
        response = _request(key, identifier, previous[0] if previous else "")
        if response.status_code == 304:
            if not previous:
                raise SourceUnavailable()
            raw = previous[2]
        else:
            raw = response.json()
            if not isinstance(raw, dict):
                raise SourceUnavailable()
        # Validate the payload before replacing a previously good cached event.
        normalize(raw, identifier)
        with _lock:
            _details[cache_key] = (wanted_etag, monotonic(), raw)
            _details.move_to_end(cache_key)
            while len(_details) > 2000:
                _details.popitem(last=False)
        return True
    except (requests.RequestException, SourceUnavailable, ValueError, KeyError, TypeError, AttributeError):
        return False
    finally:
        with _lock:
            _inflight.discard(cache_key)


def get_catalog(key, start_date="", end_date=""):
    if not key:
        raise SourceUnavailable()
    identity = sha256(key.encode()).hexdigest()
    try:
        index = _index(key, identity)
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        raise SourceUnavailable() from None
    entries = index[:1000]
    with _lock:
        def current(identifier, etag):
            record = _details.get((identity, identifier))
            return bool(record and record[0] == etag and monotonic() - record[1] < 3600)
        missing = [(identifier, etag) for identifier, etag in entries if not current(identifier, etag)]
        candidates = sorted((item for item in missing if (identity, item[0]) not in _inflight),
                            key=lambda item: _attempts.get((identity, item[0]), 0))[:40]
        for identifier, _ in candidates:
            cache_key = (identity, identifier)
            _inflight.add(cache_key)
            _attempts[cache_key] = monotonic()
            _attempts.move_to_end(cache_key)
        while len(_attempts) > 2000:
            _attempts.popitem(last=False)
    executor = ThreadPoolExecutor(max_workers=4)
    jobs = {executor.submit(_load_detail, key, identity, identifier, etag): identifier for identifier, etag in candidates}
    try:
        for job in as_completed(jobs, timeout=12):
            job.result()
    except TimeoutError:
        pass
    finally:
        for job, identifier in jobs.items():
            if job.cancel():
                with _lock:
                    _inflight.discard((identity, identifier))
        executor.shutdown(wait=False, cancel_futures=True)
    items, stale, pending = [], False, False
    with _lock:
        records = [(identifier, etag, _details.get((identity, identifier))) for identifier, etag in entries]
    for identifier, etag, record in records:
        if not record:
            pending = True
            continue
        outdated = record[0] != etag or monotonic() - record[1] >= 3600
        stale, pending = stale or outdated, pending or outdated
        items.extend(normalize(record[2], identifier))
    if entries and not any(record for _, _, record in records) and candidates and all(job.done() and not job.cancelled() for job in jobs):
        if all(not job.result() for job in jobs):
            raise SourceUnavailable()
    return {"events": [e for e in items if (not start_date or e["end"] >= start_date)
                       and (not end_date or e["start"] <= end_date)],
            "stale": stale, "pending": pending, "truncated": len(index) > 1000 or pending}
