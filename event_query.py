"""Validate filters identically for public and member views of the common catalog."""
import re
from event_months import month_range


def parse_filters(query):
    category, subcategory = query.get("category", ""), query.get("subcategory", "")
    page = query.get("page", "1")
    start, end = month_range(query.get("from_month", ""), query.get("to_month", ""))
    if (any(v and not re.fullmatch(r"[a-z0-9-]{1,80}", v) for v in (category, subcategory))
            or len(page) > 4 or not page.isascii() or not page.isdecimal() or not 1 <= int(page) <= 1000):
        raise ValueError("Invalid event filters")
    return category, subcategory, int(page), start, end
