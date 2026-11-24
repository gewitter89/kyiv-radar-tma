"""Synthetic integration: candidate -> ledger -> signed snapshot -> staging API."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from scripts.prozorro_auction_candidates import candidate
from scripts.prozorro_review_cache import apply_page
from scripts.prozorro_candidate_handoff import handoff
from scripts.prozorro_decision_ledger import record_rights, revoke_rights, decide, revoke_item, approved_rows
from scripts.prozorro_staging_export import build
from server.auction_snapshot import unseal, seal
from server import kyiv_radar_api as api
from test_prozorro_auction_candidates import payload, NOW

KEY = b"synthetic-key-for-test-only-00000"[:32].ljust(32,b"x")


def fixture(tmp_path, now=NOW):
    cache=tmp_path/"cache"; cache.mkdir(mode=0o700)
    ledger=tmp_path/"ledger"; ledger.mkdir(mode=0o700)
    p=payload()
    p["dateModified"]=now.isoformat()
    # Relative timestamps keep API tests valid whenever CI runs.
    p["tenderPeriod"]={"startDate":(now-timedelta(days=1)).isoformat(),
                       "endDate":(now+timedelta(days=1)).isoformat()}
    apply_page(cache,[p],observed_at=now,now=now)
    rows=handoff(cache,now=now)
    assert len(rows)==1
    return ledger,rows


def grant(ledger, now):
    record_rights(ledger,evidence_id="test-evidence",valid_until=now+timedelta(days=1),
                  now=now,reviewed=True)


def approve(ledger, rows, now):
    decide(ledger,rows[0],now=now,valid_until=now+timedelta(hours=2),reviewed=True)


def test_persistent_ledger_revocation_and_new_grant(tmp_path):
    ledger, rows = fixture(tmp_path)
    assert approved_rows(ledger,rows,now=NOW,enabled=True)==[]
    with pytest.raises(ValueError):
        decide(ledger,rows[0],now=NOW,valid_until=NOW+timedelta(hours=1),reviewed=True)
    grant(ledger,NOW);approve(ledger,rows,NOW)
    assert len(approved_rows(ledger,rows,now=NOW,enabled=True))==1
    revoke_item(ledger,rows[0]["auction_id"],now=NOW)
    assert approved_rows(ledger,rows,now=NOW,enabled=True)==[]
    approve(ledger,rows,NOW)
    revoke_rights(ledger,now=NOW)
    assert approved_rows(ledger,rows,now=NOW,enabled=True)==[]
    with pytest.raises(ValueError):
        grant(ledger,NOW)
    record_rights(ledger,evidence_id="test-new-grant",valid_until=NOW+timedelta(days=1),now=NOW,reviewed=True)
    assert approved_rows(ledger,rows,now=NOW,enabled=True)==[]
    with sqlite3.connect(ledger/"auction-decisions.sqlite") as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("DELETE FROM decision_event")
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE decision_event SET kind='bad'")


def test_signed_handoff_tamper_and_expiry(tmp_path):
    ledger,rows=fixture(tmp_path)
    grant(ledger,NOW);approve(ledger,rows,NOW)
    raw=build(rows,ledger,KEY,now=NOW,enabled=True)
    visible=unseal(raw,KEY,now=NOW)
    assert len(visible)==1
    assert visible[0]["valid_until"]==(NOW+timedelta(seconds=60)).isoformat()
    assert "PRIVATE" not in raw.decode()
    with pytest.raises(ValueError):
        unseal(raw,KEY,now=NOW+timedelta(seconds=60))
    tampered=json.loads(raw)
    tampered["body"]["rows"][0]["starting_bid_uah"]="1.00"
    with pytest.raises(ValueError):
        unseal(json.dumps(tampered).encode(),KEY,now=NOW)
    revoke_item(ledger,rows[0]["auction_id"],now=NOW)
    assert unseal(build(rows,ledger,KEY,now=NOW,enabled=True),KEY,now=NOW)==[]


def test_staging_api_disabled_and_no_store(tmp_path,monkeypatch):
    now=datetime.now(timezone.utc)
    ledger,rows=fixture(tmp_path,now)
    grant(ledger,now);approve(ledger,rows,now)
    private=tmp_path/"transport";private.mkdir(mode=0o700)
    snap=private/"snapshot";secret=private/"key"
    snap.write_bytes(build(rows,ledger,KEY,now=now,enabled=True))
    secret.write_bytes(KEY)
    snap.chmod(0o600);secret.chmod(0o600)
    monkeypatch.setenv("KYIV_RADAR_AUCTION_SNAPSHOT",str(snap))
    monkeypatch.setenv("KYIV_RADAR_AUCTION_KEY",str(secret))
    monkeypatch.setenv("KYIV_RADAR_AUCTIONS_PREVIEW","1")
    monkeypatch.setattr(api,"APP_ENV","production")
    client=TestClient(api.app)
    assert client.get("/api/auctions").status_code==404
    monkeypatch.setattr(api,"APP_ENV","test")
    monkeypatch.delenv("KYIV_RADAR_AUCTIONS_PREVIEW")
    assert client.get("/api/auctions").status_code==404
    monkeypatch.setenv("KYIV_RADAR_AUCTIONS_PREVIEW","1")
    response=client.get("/api/auctions")
    assert response.status_code==200 and response.headers["cache-control"]=="no-store"
    assert response.json()["auctions"][0]["auction_id"]==rows[0]["auction_id"]
    assert response.json()["coverage_complete"] is False
    assert "evidence" not in response.text and "hmac" not in response.text
    snap.write_bytes(b"broken")
    response=client.get("/api/auctions")
    assert response.status_code==503 and response.json()["auctions"]==[]
    assert str(snap) not in response.text
