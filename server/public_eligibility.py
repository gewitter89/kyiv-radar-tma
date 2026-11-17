# -*- coding: utf-8 -*-
"""Fail-closed, server-authoritative publication eligibility.

Source labels on their own never prove agency permission, ownership, recency or
rights to redistribute. This is a second gate AFTER the existing private
partner-rights/expiry/approval check (partner_visibility.py). It must apply
equally to API catalog, health counts and contact-dispatch lookup.
"""
from __future__ import annotations

from typing import Any

FIRST_PARTY = frozenset(("київ радар", "київ радар (пряма заявка)"))
LEGACY_UNLICENSED = frozenset(("olx", "dom.ria"))


def eligible_public_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("fixtureOnly") is True:
        return False
    source = str(row.get("source") or "").strip().casefold()
    if not source or source in LEGACY_UNLICENSED:
        return False

    if source in FIRST_PARTY:
        # An unreviewed first-party submission is not automatically public.
        # The moderator assigns this state at approval, with a private audit.
        return row.get("moderationStatus") == "approved"

    if source.startswith("partner:"):
        key = source.removeprefix("partner:")
        declared = str(row.get("partnerSourceKey") or "").strip().casefold()
        external = row.get("partnerExternalId")
        # The caller MUST run enforce_partner_visibility() before here.
        # Do not allow a source prefix alone to become an approved partner.
        return bool(key) and key == declared and isinstance(external, str) and bool(external.strip())

    return False


def public_eligible_rows(rows: Any) -> list[dict]:
    return [row for row in rows if eligible_public_row(row)] if isinstance(rows, list) else []
