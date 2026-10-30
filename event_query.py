"""Validate public event search filters and provider selections."""
import re
from event_months import month_range

SOURCE_NAMES = {"visit-stockholm": "Visit Stockholm", "ticketmaster": "Ticketmaster", "billetto": "Billetto",
                "tickster": "Tickster", "kulturbiljetter": "Kulturbiljetter"}


def parse_search(query):
    value = query.get("q", "")
    if not isinstance(value, str) or len(value) > 120 or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Invalid search text")
    return " ".join(value.split())


def parse_sources(query):
    if "sources" not in query:
        return None
    value = query.get("sources", "")
    if len(value) > 100 or (hasattr(query, "getlist") and len(query.getlist("sources")) != 1):
        raise ValueError("Invalid sources")
    if not value:
        return ()
    slugs = value.split(",")
    if any(slug not in SOURCE_NAMES for slug in slugs):
        raise ValueError("Invalid source")
    return tuple(name for slug, name in SOURCE_NAMES.items() if slug in slugs)


def parse_filters(query):
    category, subcategory = query.get("category", ""), query.get("subcategory", "")
    page = query.get("page", "1")
    start, end = month_range(query.get("from_month", ""), query.get("to_month", ""))
    if (any(v and not re.fullmatch(r"[a-z0-9-]{1,80}", v) for v in (category, subcategory))
            or len(page) > 4 or not page.isascii() or not page.isdecimal() or not 1 <= int(page) <= 1000):
        raise ValueError("Invalid event filters")
    return category, subcategory, int(page), start, end
