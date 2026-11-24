"""Fail-closed, read-only live status gate for first-party landlord submissions.

A "published" static JSON entry must not stay online when its underlying
landlord_submissions SQLite row is withdrawn, rejected, deleted or unavailable.
This gate runs on every /api/deals, /api/health and /api/send_contact read.
It does not mutate production DB, approve ads or infer rights for partner data.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote


OWNER_LABEL = "київ радар (пряма заявка)"


def _owner(item: object) -> bool:
    return (isinstance(item, dict)
            and str(item.get("source") or "").strip().casefold() == OWNER_LABEL)


def enforce_owner_submission_visibility(
    deals: list[dict], private_db: str | None,
) -> list[dict]:
    """Hide first-party rows unless their own private submission is published.

    Never open a missing database in create mode. If SQLite is inaccessible,
    fail closed for owner rows but preserve unrelated partner rows so their
    separate rights/evidence gate can still make its own decision.
    """
    if not isinstance(deals, list):
        return []
    owner_rows = [row for row in deals if _owner(row)]
    if not owner_rows:
        return deals
    other_rows = [row for row in deals if not _owner(row)]
    if not isinstance(private_db, str) or not private_db:
        return other_rows
    try:
        original = Path(private_db).expanduser()
        if original.is_symlink() or not original.is_file():
            return other_rows
        target = original.resolve(strict=True)
        uri = "file:" + quote(str(target), safe="/") + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=3.0)) as conn:
            status_by_id = {}
            for row in owner_rows:
                submission_id = row.get("submission_id")
                if type(submission_id) is not int or submission_id <= 0:
                    continue
                if submission_id not in status_by_id:
                    record = conn.execute(
                        "SELECT status FROM landlord_submissions WHERE id = ?",
                        (submission_id,),
                    ).fetchone()
                    status_by_id[submission_id] = record[0] if record else None
    except (OSError, ValueError, sqlite3.Error):
        return other_rows

    # Do not allow a stale catalog entry to resurrect a closed submission.
    # Keep original order, including unrelated partner rows.
    return [
        row for row in deals
        if not _owner(row) or (
            type(row.get("submission_id")) is int
            and status_by_id.get(row["submission_id"]) == "published"
        )
    ]
