"""Conservative room-count conflict detector for permissioned private feeds.

This is NOT a scraper, NLP ownership check or proof of current OLX data.
Only explicit room-count phrases in authorized title/description are compared
to structured room metadata; unseen pages are never inferred from URLs.
Private text is inspected in memory and NOT copied into inventory database.
"""
from __future__ import annotations

import re
from typing import Any

MAX_CLAIM_TEXT = 8192
NUMERIC_ROOMS = re.compile(
    r"(?<![\w])(?P<count>1[0-5]|[1-9])\s*"
    r"(?:[-–‑]?\s*[хx]\s*)?[-–‑]?\s*"
    r"(?:к(?![\w])|кімн(?:ат\w*)?\.?|комн(?:ат\w*)?\.?)",
    re.IGNORECASE,
)
WORDS = (
    (1, re.compile(r"(?<!\w)(?:однокімнатн\w*|однокомнатн\w*|однушк\w*)", re.I)),
    (2, re.compile(r"(?<!\w)(?:двокімнатн\w*|двохкімнатн\w*|двухкомнатн\w*|двушк\w*)", re.I)),
    (3, re.compile(r"(?<!\w)(?:трикімнатн\w*|трьохкімнатн\w*|трехкомнатн\w*|трёхкомнатн\w*)", re.I)),
    (4, re.compile(r"(?<!\w)(?:чотирикімнатн\w*|чотирьохкімнатн\w*|четырехкомнатн\w*|четырёхкомнатн\w*)", re.I)),
    (5, re.compile(r"(?<!\w)(?:пятикомнатн\w*|п'ятикімнатн\w*|п’ятикімнатн\w*|пятікімнатн\w*)", re.I)),
)


def explicit_room_claims(*texts: Any) -> set[int]:
    """Only explicit literal counts. Studio, bedroom and floor are not rooms."""
    claims: set[int] = set()
    for value in texts:
        if not isinstance(value, str):
            continue
        text = value[:MAX_CLAIM_TEXT]
        claims.update(int(match.group("count")) for match in NUMERIC_ROOMS.finditer(text))
        for count, pattern in WORDS:
            if pattern.search(text):
                claims.add(count)
    return claims


def has_room_conflict(rooms: Any, *texts: Any) -> bool:
    """Disagreement between explicit claims or a supplied structured count."""
    claims = explicit_room_claims(*texts)
    if len(claims) > 1:
        return True
    return bool(claims and type(rooms) is int and rooms > 0 and rooms not in claims)


def validate_feed_rooms(row: dict, structured_rooms: int | None) -> None:
    """Block conflicting metadata during permitted intake without storing text.

    Missing title/description is not proof of correctness. An unprovided
    structured count stays unknown: never manufacture a number from prose.
    """
    values = []
    for key in ("title", "description"):
        raw = row.get(key)
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str) or len(raw) > MAX_CLAIM_TEXT:
            raise ValueError("Invalid or oversized source room-claim field")
        values.append(raw)
    if has_room_conflict(structured_rooms, *values):
        raise ValueError("Room count conflicts with explicit source title/description")
