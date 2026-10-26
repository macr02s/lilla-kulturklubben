"""Inclusive calendar-month boundaries shared by both event providers."""
from calendar import monthrange
import re


def month_range(first="", last=""):
    if not first and not last:
        return "", ""
    for value in (first, last):
        if not re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", value):
            raise ValueError("Invalid month")
        if not 2000 <= int(value[:4]) <= 2100:
            raise ValueError("Invalid year")
    if first > last:
        raise ValueError("Reversed month range")
    year, month = map(int, last.split("-"))
    return first + "-01", last + f"-{monthrange(year, month)[1]:02d}"
