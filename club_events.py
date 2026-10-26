"""Common event catalog: provider adapters, strict geography and conservative deduplication."""
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
import re
from threading import Lock
from time import monotonic
import unicodedata
from zoneinfo import ZoneInfo

import billetto_events as billetto
import ticketmaster_events as ticketmaster
import visit_stockholm as visit

_cache, _lock = OrderedDict(), Lock()
PRIORITY = {"Ticketmaster": 0, "Billetto": 1, "Visit Stockholm": 2}
LABELS = {"music": "Musik", "stage": "Scen & film", "art": "Utställningar",
          "sport": "Sport & hälsa", "food": "Mat & dryck", "family": "Familj", "other": "Övrigt"}


class SourceUnavailable(Exception):
    pass


def text_key(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(re.sub(r"[^\w\s]", " ", "".join(c for c in value if not unicodedata.combining(c))).replace("_", " ").split())


def category_id(label):
    key = text_key(label)
    for category, words in {
        "music": {"music", "musik"}, "stage": {"scenkonst", "scen film", "arts theatre", "film", "theatre", "comedy", "scen bildkonst", "performing arts"},
        "art": {"utstallningar", "exhibitions", "art"}, "sport": {"sport", "sports", "sport halsa"},
        "food": {"mat dryck", "food drink"}, "family": {"familj", "family"},
    }.items():
        if key in words:
            return category
    return "other"


def normalize(raw, source):
    if not isinstance(raw, dict) or text_key(raw.get("city")) != "stockholm":
        return None
    url = {"Visit Stockholm": visit.source_url, "Ticketmaster": ticketmaster.source_url,
           "Billetto": billetto.event_url}[source](raw.get("url"))
    title, venue = str(raw.get("title") or "").strip(), str(raw.get("venue") or "").strip()
    try:
        start = date.fromisoformat(raw.get("start") or "").isoformat()
        end = date.fromisoformat(raw.get("end") or start).isoformat()
    except (ValueError, TypeError):
        return None
    if not title or not url or end < start:
        return None
    clock = raw.get("time") or ""
    if not isinstance(clock, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", clock):
        clock = ""
    image = raw.get("image") or ""
    image = visit.source_url(image) if source == "Visit Stockholm" else ticketmaster.source_url(image, image=True) if source == "Ticketmaster" else ""
    category = category_id(raw.get("category"))
    return {"title": title, "url": url, "venue": venue, "city": "Stockholm", "start": start, "end": end,
            "time": clock, "category_id": category, "category": LABELS[category], "genre": str(raw.get("genre") or ""),
            "genre_id": text_key(raw.get("genre")).replace(" ", "-")[:80], "image": image,
            "alt": str(raw.get("alt") or title), "credit": str(raw.get("credit") or ""),
            "link_source": source, "sources": [source]}


def deduplicate(events):
    buckets = defaultdict(list)
    for event in events:
        venue = text_key(event["venue"])
        # Missing places cannot be assumed to be the same venue.
        place = venue or event["url"]
        key = (text_key(event["title"]), place, event["start"], event["end"])
        buckets[key].append(event)
    merged = []
    for key, bucket in buckets.items():
        known_times = {e["time"] for e in bucket if e["time"]}
        groups = defaultdict(list)
        for event in bucket:
            # Do not collapse matinee/evening performances, or assign an undated time to either one.
            clock = event["time"] or (next(iter(known_times)) if len(known_times) == 1 else "")
            identity = clock if clock or len(known_times) <= 1 else event["link_source"] + event["url"]
            groups[identity].append(event)
        for clock, group in groups.items():
            group.sort(key=lambda e: (PRIORITY[e["link_source"]], e["url"]))
            best = deepcopy(group[0])
            best["sources"] = sorted({s for e in group for s in e["sources"]})
            for field in ("image", "time", "venue", "genre", "genre_id"):
                if not best[field]:
                    replacement = next((e for e in group if e[field]), None)
                    if replacement:
                        best[field] = replacement[field]
                        if field == "image":
                            best["credit"], best["alt"] = replacement["credit"], replacement["alt"]
            best["id"] = sha256(repr((key, clock)).encode()).hexdigest()[:24]
            merged.append(best)
    return sorted(merged, key=lambda e: (e["start"], e["time"], text_key(e["title"]), e["id"]))


def _visit_catalog(settings, start_date, end_date):
    items, page, stale = [], 1, False
    for _ in range(10):
        data = visit.get_events(page=page, start_date=start_date, end_date=end_date, page_size=100)
        items.extend(data["events"])
        stale = stale or data.get("stale", False)
        if not data["next"]:
            return {"events": items, "truncated": False, "stale": stale}
        page = data["next"]
    return {"events": items, "truncated": True, "stale": stale}


def _ticketmaster_catalog(settings, start_date, end_date):
    return ticketmaster.get_events(settings["TICKETMASTER_API_KEY"], start_date=start_date, end_date=end_date, page_size=1000)


def _billetto_catalog(settings, start_date, end_date):
    return billetto.get_catalog(settings["BILLETTO_API_KEYPAIR"], start_date, end_date)


def providers(settings):
    active = {"Visit Stockholm": _visit_catalog}
    if settings.get("TICKETMASTER_API_KEY"):
        active["Ticketmaster"] = _ticketmaster_catalog
    if settings.get("BILLETTO_API_KEYPAIR"):
        active["Billetto"] = _billetto_catalog
    return active


def _catalog(settings, start_date, end_date):
    items, unavailable, successful = [], [], []
    truncated, stale = False, False
    today = datetime.now(ZoneInfo("Europe/Stockholm")).date().isoformat()
    with ThreadPoolExecutor(max_workers=3) as executor:
        jobs = {name: executor.submit(fetch, settings, start_date, end_date) for name, fetch in providers(settings).items()}
        for name, job in jobs.items():
            try:
                data = job.result()
            except (visit.SourceUnavailable, ticketmaster.SourceUnavailable, billetto.SourceUnavailable):
                unavailable.append(name)
                continue
            successful.append(name)
            truncated = truncated or data.get("truncated", False)
            stale = stale or data.get("stale", False)
            for raw in data["events"]:
                event = normalize(raw, name)
                if (event and event["end"] >= (start_date or today)
                        and (not end_date or event["start"] <= end_date)):
                    items.append(event)
    if not successful:
        raise SourceUnavailable()
    events = deduplicate(items)
    categories = {}
    for event in events:
        children = categories.setdefault(event["category_id"], {})
        if event["genre_id"]:
            children[event["genre_id"]] = event["genre"]
    return {"events": events, "categories": [{"slug": slug, "title": LABELS[slug], "subcategories": [
        {"slug": child, "title": title} for child, title in sorted(children.items(), key=lambda i: i[1])]}
        for slug, children in sorted(categories.items(), key=lambda i: LABELS[i[0]])],
        "unavailable_sources": unavailable, "sources": successful, "stale": stale, "truncated": truncated,
        "combined": True, "updated": datetime.now(timezone.utc).isoformat()}


def get_events(settings, category="", subcategory="", page=1, start_date="", end_date=""):
    credentials = tuple(settings.get(k, "") for k in ("TICKETMASTER_API_KEY", "BILLETTO_API_KEYPAIR"))
    key = (sha256(repr(credentials).encode()).hexdigest(), start_date, end_date)
    with _lock:
        cached = _cache.get(key)
        ttl = 60 if cached and cached[1]["unavailable_sources"] else 600
        if cached and monotonic() - cached[0] < ttl:
            data = cached[1]
        else:
            try:
                data = _catalog(settings, start_date, end_date)
            except SourceUnavailable:
                if not cached or monotonic() - cached[0] >= 3600:
                    raise
                data = deepcopy(cached[1])
                data["stale"] = True
                data["unavailable_sources"] = list(providers(settings))
            else:
                _cache[key] = (monotonic(), data)
                _cache.move_to_end(key)
                while len(_cache) > 16:
                    _cache.popitem(last=False)
        items = [e for e in data["events"] if (not category or e["category_id"] == category)
                 and (not subcategory or e["genre_id"] == subcategory)]
        offset = (page - 1) * 9
        return deepcopy({**data, "events": items[offset:offset + 9], "count": len(items), "page": page,
                         "next": page + 1 if offset + 9 < len(items) else None})
