"""Private append-only operator decision ledger; never reachable via HTTP."""
import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from .prozorro_review_cache import private_directory
from .prozorro_review_projection import SCOPE, fingerprint, project
from .prozorro_auction_candidates import _aware, _utc, AUCTION_ID

MAX_EVENTS = 10000
MAX_BYTES = 8 * 1024 * 1024


@contextmanager
def connect(directory):
    path = private_directory(directory) / "auction-decisions.sqlite"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > MAX_BYTES:
            raise ValueError("Unsafe decision ledger")
    finally:
        os.close(fd)
    conn = sqlite3.connect(path, timeout=3)
    try:
        size = conn.execute("PRAGMA page_size").fetchone()[0]
        conn.execute(f"PRAGMA max_page_count={MAX_BYTES // size}")
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS decision_event (
            seq INTEGER PRIMARY KEY, kind TEXT NOT NULL, object_id TEXT NOT NULL,
            occurred TEXT NOT NULL, payload TEXT NOT NULL
          );
          CREATE TRIGGER IF NOT EXISTS decision_no_update BEFORE UPDATE ON decision_event
          BEGIN SELECT RAISE(ABORT, 'immutable event'); END;
          CREATE TRIGGER IF NOT EXISTS decision_no_delete BEFORE DELETE ON decision_event
          BEGIN SELECT RAISE(ABORT, 'immutable event'); END;
        """)
        yield conn
    finally:
        conn.close()


def _append(conn, kind, key, payload, now):
    if conn.execute("SELECT COUNT(*) FROM decision_event").fetchone()[0] >= MAX_EVENTS:
        raise ValueError("Ledger capacity reached")
    last = conn.execute("SELECT occurred FROM decision_event ORDER BY seq DESC LIMIT 1").fetchone()
    if last and _utc(last[0]) > now:
        raise ValueError("Clock moved backwards")
    conn.execute("INSERT INTO decision_event(kind,object_id,occurred,payload) VALUES(?,?,?,?)",
                 (kind,key,now.isoformat(),json.dumps(payload,sort_keys=True)))


def _state(conn, now):
    rights = None
    decisions = {}
    for kind, key, occurred, raw in conn.execute("SELECT kind,object_id,occurred,payload FROM decision_event ORDER BY seq"):
        if _utc(occurred) > now:
            raise ValueError("Future decision")
        value = json.loads(raw)
        if kind == "rights":
            rights = value
            decisions = {}  # New grant or revocation invalidates prior approvals.
        elif kind == "decision":
            decisions[key] = value
        else:
            raise ValueError("Unknown decision event")
    return rights, decisions


def record_rights(directory, *, evidence_id, valid_until, now, reviewed=False):
    now, until = _aware(now), _aware(valid_until)
    if reviewed is not True or not isinstance(evidence_id,str) or not 1 <= len(evidence_id) <= 128 or not now < until <= now+timedelta(days=90):
        raise ValueError("Explicit reviewed rights required")
    with connect(directory) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM decision_event WHERE kind='rights' AND object_id=?", (evidence_id,)).fetchone():
            raise ValueError("Rights evidence cannot be reused")
        _append(conn,"rights",evidence_id,{"status":"approved","scope":SCOPE,
                "evidence_id":evidence_id,"valid_from":now.isoformat(),"valid_until":until.isoformat()},now)


def revoke_rights(directory, *, now):
    now = _aware(now)
    with connect(directory) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        rights,_ = _state(conn,now)
        if rights is None:
            raise ValueError("No existing rights")
        _append(conn,"rights",rights["evidence_id"],dict(rights,status="revoked"),now)


def decide(directory, row, *, now, valid_until, reviewed=False):
    now, until = _aware(now), _aware(valid_until)
    if reviewed is not True or not now < until <= now+timedelta(days=7):
        raise ValueError("Explicit item approval required")
    key = row["auction_id"]
    with connect(directory) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        rights,_ = _state(conn,now)
        if not rights:
            raise ValueError("No rights")
        decision = {"status":"approved","fingerprint":fingerprint(row),
                    "rights_evidence_id":rights["evidence_id"],"approved_at":now.isoformat(),
                    "valid_until":until.isoformat()}
        if until > _utc(rights["valid_until"]) or not project([row],{key:decision},rights,now=now,enabled=True):
            raise ValueError("Candidate is not eligible")
        _append(conn,"decision",key,decision,now)


def revoke_item(directory, key, *, now):
    now = _aware(now)
    if not isinstance(key,str) or not AUCTION_ID.fullmatch(key):
        raise ValueError("Invalid ID")
    with connect(directory) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        _append(conn,"decision",key,{"status":"revoked"},now)


def approved_rows(directory, candidates, *, now, enabled=False):
    if enabled is not True:
        return []
    now = _aware(now)
    with connect(directory) as conn:
        rights, decisions = _state(conn,now)
    return project(candidates,decisions,rights,now=now,enabled=True)
