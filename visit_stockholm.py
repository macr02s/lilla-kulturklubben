"""Small server-side adapter for Visit Stockholm's public event listing."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
from threading import Lock
from time import monotonic
from urllib.error import URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

BASE = "https://www.visitstockholm.se"
TTL = 600
STALE_TTL = 3600
_cache = OrderedDict()
_lock = Lock()


class SourceUnavailable(Exception):
    pass


def source_url(value):
    """Only expose HTTPS links on the source's own domain."""
    if not isinstance(value, str) or not value:
        return ""
    url = urljoin(BASE, value)
    parts = urlsplit(url)
    return url if parts.scheme == "https" and parts.netloc == "www.visitstockholm.se" else ""


def _fetch(params):
    req = Request(BASE + "/api/v1/singulareventdates/?" + urlencode(params),
                  headers={"Accept": "application/json", "Accept-Encoding": "gzip",
                           "User-Agent": "LillaKulturklubben/1.0"})
    with urlopen(req, timeout=10) as response:
        body = response.read(5_000_001)
    if len(body) > 5_000_000:
        raise ValueError("Source response too large")
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return json.loads(body)


def get_events(category="", subcategory="", page=1):
    key = (category, subcategory, page)
    # Serialize cache fills to avoid sending duplicate requests under load.
    with _lock:
        cached = _cache.get(key)
        if cached and monotonic() - cached[0] < TTL:
            _cache.move_to_end(key)
            return deepcopy(cached[1])
        params = {"page": page, "size": 9}
        if category:
            params["categories"] = category
        if subcategory:
            params["subcategory"] = subcategory
        try:
            raw = _fetch(params)
            categories = [{"slug": c["slug"], "title": c["title"],
                           "subcategories": [{"slug": s["slug"], "title": s["title"]}
                                             for s in c.get("subcategories", [])
                                             if s.get("has_events", True)]}
                          for c in raw["meta"]["categories"]]
            items = []
            for event in raw["results"]:
                href = source_url(event.get("href"))
                if not href:
                    continue
                image = event.get("image") or {}
                thumbnail = image.get("renditions", {}).get("small", {})
                items.append({"title": event["title"], "url": href,
                              "image": source_url(thumbnail.get("src")),
                              "alt": image.get("alt") or "",
                              "credit": image.get("caption") or "",
                              "category": (event.get("category") or {}).get("title", ""),
                              "venue": event.get("venue_name") or "",
                              "start": event.get("start_date"), "end": event.get("end_date")})
            next_page = raw.get("next")
            data = {"categories": categories, "events": items, "count": raw["count"],
                    "next": next_page if isinstance(next_page, int) and page < next_page <= 1000 else None,
                    "page": page, "stale": False,
                    "updated": datetime.now(timezone.utc).isoformat()}
        except (URLError, OSError, ValueError, KeyError, TypeError) as exc:
            if cached and monotonic() - cached[0] < STALE_TTL:
                fallback = deepcopy(cached[1])
                fallback["stale"] = True
                return fallback
            raise SourceUnavailable() from exc
        _cache[key] = (monotonic(), data)
        _cache.move_to_end(key)
        while len(_cache) > 128:
            _cache.popitem(last=False)
        return deepcopy(data)
