#!/usr/bin/env python3
"""Private source-rights lifecycle for permissioned real-estate inventory.

A source can be revoked, but never reactivated by ingestion of an old grant.
No public data export, no network calls, and no automatic listing approval.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
REVOKE_REASONS = {"partner_request", "contract_expired", "compliance_hold", "operator_hold"}


def private_existing_db(value: Path) -> Path:
    path = value.expanduser()
    if path.is_symlink():
        raise ValueError("Symlink database path forbidden")
    resolved = path.resolve()
    if resolved.is_relative_to(REPO_ROOT) or not resolved.is_file():
        raise ValueError("Existing private inventory database required")
    return resolved


def register_rights(conn: sqlite3.Connection, agreement: dict, now: datetime) -> None:
    """Run within the caller's SQLite BEGIN IMMEDIATE transaction.

    The JSON permission attestation only records operator review; it does not
    prove ownership of the rights or allow publication on its own.
    """
    source = agreement["source_key"]
    ref = agreement["agreement_ref"]
    end = agreement["valid_until"]
    row = conn.execute(
        "SELECT agreement_ref, valid_until, status FROM source_rights WHERE source=?",
        (source,),
    ).fetchone()
    timestamp = now.astimezone(timezone.utc).isoformat()
    if row is None:
        conn.execute(
            "INSERT INTO source_rights(source,agreement_ref,valid_until,status,updated_at) "
            "VALUES (?,?,?,'active',?)", (source, ref, end, timestamp),
        )
        # An older approval is not transferred to a newly registered source
        # contract. Human review is required after the first provenance gate.
        conn.execute(
            "UPDATE inventory SET review_status='needs_review' "
            "WHERE source=? AND review_status='approved'", (source,),
        )
        conn.execute(
            "INSERT INTO source_rights_audit(source,event,at_utc) VALUES (?,'registered',?)",
            (source, timestamp),
        )
        return
    previous_ref, previous_end, status = row
    if status != "active":
        raise ValueError("Source disabled by private operator; ingestion blocked")
    if previous_ref != ref:
        raise ValueError("Agreement replacement requires separate operator review")
    if end > previous_end:
        raise ValueError("Contract extension requires separate operator review")
    if end < previous_end:
        conn.execute(
            "UPDATE source_rights SET valid_until=?,updated_at=? WHERE source=?",
            (end, timestamp, source),
        )
        conn.execute(
            "INSERT INTO source_rights_audit(source,event,at_utc) VALUES (?,'shortened',?)",
            (source, timestamp),
        )


def revoke_source(database: Path, source: str, reason: str,
                  *, now: datetime | None = None) -> dict:
    """Irreversibly disable one source until a separate reviewed migration.

    Repeated revocations are idempotent. Source ID and enumerated reason only:
    no confidential contract or owner data is written to CLI output.
    """
    if not isinstance(source, str) or SOURCE_RE.fullmatch(source) is None:
        raise ValueError("Invalid source key")
    if reason not in REVOKE_REASONS:
        raise ValueError("Use an approved non-sensitive revoke reason")
    target = private_existing_db(database)
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    with sqlite3.connect(target, timeout=30) as conn:
        conn.execute("BEGIN IMMEDIATE")
        entry = conn.execute(
            "SELECT status FROM source_rights WHERE source=?", (source,),
        ).fetchone()
        if entry is None:
            raise ValueError("Unknown source; no revocation applied")
        if entry[0] == "revoked":
            return {"source": source, "revoked": True, "already_revoked": True,
                    "approvals_reset": 0, "publications": 0}
        update = conn.execute(
            "UPDATE source_rights SET status='revoked',updated_at=? WHERE source=? "
            "AND status='active'", (stamp, source),
        )
        if update.rowcount != 1:
            raise ValueError("Unexpected source state")
        reset = conn.execute(
            "UPDATE inventory SET review_status='needs_review' "
            "WHERE source=? AND review_status='approved'", (source,),
        )
        conn.execute(
            "INSERT INTO source_rights_audit(source,event,at_utc,reason_code) "
            "VALUES (?,'revoked',?,?)", (source, stamp, reason),
        )
        return {"source": source, "revoked": True, "already_revoked": False,
                "approvals_reset": reset.rowcount, "publications": 0}


def assess_source(database: Path, source: str, *, now: datetime | None = None) -> dict:
    """Private *inventory* check. Never claims a listing is public-ready."""
    if not isinstance(source, str) or SOURCE_RE.fullmatch(source) is None:
        raise ValueError("Invalid source key")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
    with sqlite3.connect(private_existing_db(database), timeout=30) as conn:
        right = conn.execute(
            "SELECT valid_until,status FROM source_rights WHERE source=?",
            (source,),
        ).fetchone()
        total = conn.execute(
            "SELECT COUNT(*) FROM inventory WHERE source=?", (source,),
        ).fetchone()[0]
        reviewed = conn.execute(
            "SELECT COUNT(*) FROM inventory WHERE source=? AND review_status='approved'",
            (source,),
        ).fetchone()[0]
    active = bool(right is not None and right[1] == "active" and right[0] >= current)
    state = ("missing" if right is None else "revoked" if right[1] == "revoked"
             else "expired" if right[0] < current else "active")
    return {"source": source, "rights_state": state, "ingestion_authorized": active,
            "inventory_records": total, "reviewed_records": reviewed,
            "publications": 0, "public_listing_verified": False}


def main() -> int:
    p = argparse.ArgumentParser(description="Private source inventory rights controls")
    commands = p.add_subparsers(dest="action", required=True)
    for action in ("revoke", "assess"):
        command = commands.add_parser(action)
        command.add_argument("--database", type=Path, required=True)
        command.add_argument("--source", required=True)
        if action == "revoke":
            command.add_argument("--reason", required=True, choices=sorted(REVOKE_REASONS))
    args = p.parse_args()
    try:
        result = (revoke_source(args.database, args.source, args.reason)
                  if args.action == "revoke"
                  else assess_source(args.database, args.source))
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, sqlite3.Error):
        # Never leak private db path, raw SQL or contract data to CLI logs.
        print('{"ok":false,"error":"Private source rights operation rejected"}')
        return 2


if __name__ == "__main__":
    sys.exit(main())
