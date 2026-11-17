"""Evidence-gated, read-only moderation decisions for rental listings.

No source data is proof of actual availability, owner identity or commission.
The private reviewer register may be maintained by an authorized operator,
never by public user input. Proof material stays off the public web.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

REVIEW_MAX_AGE_DAYS = 14
PRIVATE_STATES = {"hidden", "removed", "withdrawn", "archived"}
IMPORTED_SOURCES = {"OLX", "DOM.RIA"}


def _read_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        instant = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if instant.tzinfo is None:
        return None
    return instant.astimezone(timezone.utc)


def _valid_evidence(check: Any, now: datetime) -> datetime | None:
    """Require a real reviewer, private evidence reference and fresh timestamp."""
    if not isinstance(check, dict):
        return None
    if not isinstance(check.get("reviewer"), str) or not check["reviewer"].strip():
        return None
    if not isinstance(check.get("evidence_ref"), str) or not check["evidence_ref"].strip():
        return None
    checked = _read_date(check.get("checked_at"))
    if checked is None:
        return None
    age = now - checked
    if age < -timedelta(minutes=5) or age > timedelta(days=REVIEW_MAX_AGE_DAYS):
        return None
    return checked


def load_private_register(path: str | None) -> dict[str, dict]:
    """Fail closed on malformed data; do not log private evidence contents."""
    if not path:
        return {}
    try:
        source = Path(path)
        if not source.is_file() or source.stat().st_size > 2_000_000:
            return {}
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return {}
        records = payload.get("listings")
        if not isinstance(records, dict):
            return {}
        return {key: value for key, value in records.items()
                if isinstance(key, str) and key.isdecimal() and isinstance(value, dict)}
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}


def public_listing_view(
    catalog: list[dict], private_reviews: Mapping[str, dict] | None = None,
    *, now: datetime | None = None,
) -> list[dict]:
    """Produce public-safe listing metadata; preserve original source records."""
    now = now or datetime.now(timezone.utc)
    reviews = private_reviews or {}
    result = []
    for source in catalog:
        if not isinstance(source, dict):
            continue
        deal_id = source.get("id")
        if type(deal_id) is not int or deal_id <= 0:
            continue
        review = reviews.get(str(deal_id), {})
        if not isinstance(review, dict):
            review = {}
        state = str(review.get("state", "")).strip().lower()
        native_state = str(source.get("status", "")).strip().lower()
        if state in PRIVATE_STATES or native_state in PRIVATE_STATES:
            continue

        deal = dict(source)
        # Only this module issues evidence-backed status markers.
        deal.pop("reviewedByRadar", None)
        source_name = str(deal.get("source", "")).strip().upper()
        imported = (source_name in IMPORTED_SOURCES or source_name.startswith("PARTNER:")
                    or deal.get("partnerSourceKey") is not None
                    or deal.get("partnerExternalId") is not None)
        if imported:
            # Imported text and site metadata are not our own verification.
            deal["actualityConfirmed"] = False
            deal["isOwnerVerified"] = False
            deal["contactVerified"] = False
            deal["commissionVerified"] = False
            deal["locationVerified"] = False
            deal.pop("verifiedAt", None)
            deal.pop("phoneVerifiedAt", None)
            deal["verificationStatus"] = "unverified"
            deal["statusLabel"] = "Актуальність не перевірено"

        if state == "verified":
            availability = review.get("availability")
            checked = _valid_evidence(availability, now)
            if checked and isinstance(availability, dict) and availability.get("available") is True:
                deal["actualityConfirmed"] = True
                deal["reviewedByRadar"] = True
                deal["verifiedAt"] = checked.isoformat(timespec="seconds")
                deal["verificationStatus"] = "availability_verified"
                deal["statusLabel"] = "Наявність перевірено"
            # Distinct evidence for each individual claim; availability is not
            # evidence of ownership, commission, location or working internet.
            for private_key, public_key in (
                ("ownership", "isOwnerVerified"),
                ("contact", "contactVerified"),
                ("zero_commission", "commissionVerified"),
                ("location", "locationVerified"),
            ):
                part = review.get(private_key)
                valid = _valid_evidence(part, now) is not None
                if valid and isinstance(part, dict) and part.get("confirmed") is True:
                    deal[public_key] = True

        # Never return notes/reviewer/evidence to an API caller.
        result.append(deal)
    return result
