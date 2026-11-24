"""Synthetic integration: candidate -> ledger -> signed snapshot -> staging API."""
import json
import os
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


def test_production_release_gate(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    ledger, rows = fixture(tmp_path, now)
    grant(ledger, now)
    approve(ledger, rows, now)
    private = tmp_path / "transport"
    private.mkdir(mode=0o700)
    snap = private / "snapshot"
    secret = private / "key"
    snap.write_bytes(build(rows, ledger, KEY, now=now, enabled=True))
    secret.write_bytes(KEY)
    snap.chmod(0o600)
    secret.chmod(0o600)

    monkeypatch.setenv("KYIV_RADAR_AUCTION_SNAPSHOT", str(snap))
    monkeypatch.setenv("KYIV_RADAR_AUCTION_KEY", str(secret))
    monkeypatch.setattr(api, "APP_ENV", "production")

    client = TestClient(api.app)

    # 1. In production, default is 404 (disabled) for GET, HEAD, and plain OPTIONS
    assert client.get("/api/auctions").status_code == 404
    assert client.head("/api/auctions").status_code == 404
    assert client.options("/api/auctions").status_code == 404

    # 2. Preview flag must NOT enable production route
    monkeypatch.setenv("KYIV_RADAR_AUCTIONS_PREVIEW", "1")
    assert client.get("/api/auctions").status_code == 404

    # 3. Unknown APP_ENV must default to production (fail-safe)
    monkeypatch.setattr(api, "APP_ENV", "unrecognized_custom_env")
    assert client.get("/api/auctions").status_code == 404

    # 4. Explicit production release flag enables the route
    monkeypatch.setenv("KYIV_RADAR_AUCTIONS_RELEASE", "1")
    assert client.get("/api/auctions").status_code == 404
    monkeypatch.setattr(api, "APP_ENV", "production")
    resp = client.get("/api/auctions")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert resp.json()["available"] is True
    assert len(resp.json()["auctions"]) == 1

    # HEAD returns 200
    assert client.head("/api/auctions").status_code == 200

    # Plain OPTIONS returns 204 when gate is open
    resp_options = client.options("/api/auctions")
    assert resp_options.status_code == 204

    # 5. Strict CORS preflight testing via FastAPI CORSMiddleware
    # Allowed origin: https://gewitter89.github.io
    cors_allowed = client.options("/api/auctions", headers={
        "Origin": "https://gewitter89.github.io",
        "Access-Control-Request-Method": "GET"
    })
    assert cors_allowed.status_code in (200, 204)
    assert cors_allowed.headers.get("access-control-allow-origin") == "https://gewitter89.github.io"

    # Disallowed origin: https://evil.com
    cors_disallowed = client.options("/api/auctions", headers={
        "Origin": "https://evil.com",
        "Access-Control-Request-Method": "GET"
    })
    assert cors_disallowed.headers.get("access-control-allow-origin") is None


def test_atomic_publish(tmp_path):
    now = datetime.now(timezone.utc)
    ledger, rows = fixture(tmp_path, now)
    grant(ledger, now)
    approve(ledger, rows, now)
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(json.dumps(rows))
    candidates_file.chmod(0o600)

    key_file = tmp_path / "secret.key"
    key_file.write_bytes(KEY)
    key_file.chmod(0o600)

    published_dir = tmp_path / "published"
    # Target directory must exist beforehand; cannot auto-create arbitrary dirs
    from scripts.prozorro_atomic_publish import publish
    with pytest.raises(ValueError, match="Target directory must exist"):
        publish(str(candidates_file), str(ledger), str(key_file), str(published_dir / "snapshot.bin"), now=now)

    published_dir.mkdir(mode=0o700)
    out_file = published_dir / "snapshot.bin"

    # 1. enabled defaults to False (zero rows published)
    count, size = publish(str(candidates_file), str(ledger), str(key_file), str(out_file), now=now)
    assert count == 0
    from server.auction_snapshot import load
    assert load(str(out_file), str(key_file), now=now) == []

    # 2. explicit enabled=True publishes approved candidate
    count, size = publish(str(candidates_file), str(ledger), str(key_file), str(out_file), now=now, enabled=True)
    assert count == 1
    assert size > 0
    assert out_file.exists()
    assert (out_file.stat().st_mode & 0o777) in (0o640, 0o600)

    unsealed = load(str(out_file), str(key_file), now=now)
    assert len(unsealed) == 1
    assert unsealed[0]["auction_id"] == rows[0]["auction_id"]

    # 3. Reject symlink target
    symlink_target = published_dir / "symlink_snapshot.bin"
    symlink_target.symlink_to(out_file)
    with pytest.raises(ValueError, match="cannot be a symlink"):
        publish(str(candidates_file), str(ledger), str(key_file), str(symlink_target), now=now, enabled=True)

    # 4. Reject hardlinked target
    hardlink_target = published_dir / "hardlink_snapshot.bin"
    os.link(out_file, hardlink_target)
    with pytest.raises(ValueError, match="cannot have hard links"):
        publish(str(candidates_file), str(ledger), str(key_file), str(hardlink_target), now=now, enabled=True)
    hardlink_target.unlink()

    # 5. Concurrent publishers serialization
    from concurrent.futures import ThreadPoolExecutor
    def run_pub(n):
        return publish(str(candidates_file), str(ledger), str(key_file), str(out_file), now=now, enabled=True)

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(run_pub, range(4)))
    assert all(r[0] == 1 for r in results)
    assert len(load(str(out_file), str(key_file), now=now)) == 1


def test_continuous_publisher_and_kill_switch(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    ledger, rows = fixture(tmp_path, now)
    grant(ledger, now)
    approve(ledger, rows, now)

    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(json.dumps(rows))
    candidates_file.chmod(0o600)

    key_file = tmp_path / "secret.key"
    key_file.write_bytes(KEY)
    key_file.chmod(0o600)

    transport_dir = tmp_path / "transport"
    transport_dir.mkdir(mode=0o700)
    out_file = transport_dir / "snapshot.bin"
    kill_switch_file = transport_dir / ".kill_switch"

    from scripts.prozorro_continuous_publisher import run_continuous_publisher

    # 1. Bounded run of 2 iterations publishes snapshot cleanly
    res = run_continuous_publisher(
        str(candidates_file), str(ledger), str(key_file), str(out_file),
        interval=0.01, kill_switch_path=str(kill_switch_file), max_runs=2, enabled=True
    )
    assert res == "completed"
    assert out_file.exists()

    # 2. Test loopback HTTP endpoint returns 200 with snapshot
    monkeypatch.setenv("KYIV_RADAR_AUCTION_SNAPSHOT", str(out_file))
    monkeypatch.setenv("KYIV_RADAR_AUCTION_KEY", str(key_file))
    monkeypatch.setattr(api, "APP_ENV", "production")
    monkeypatch.setenv("KYIV_RADAR_AUCTIONS_RELEASE", "1")
    client = TestClient(api.app)
    assert client.get("/api/auctions").status_code == 200

    # 3. The API itself blocks immediately, even before the publisher wakes.
    kill_switch_file.touch()
    assert out_file.exists()
    assert client.get("/api/auctions").status_code == 503
    assert client.head("/api/auctions").status_code == 503
    res_kill = run_continuous_publisher(
        str(candidates_file), str(ledger), str(key_file), str(out_file),
        interval=0.01, kill_switch_path=str(kill_switch_file), max_runs=2, enabled=True
    )
    assert res_kill == "kill_switch_triggered"
    assert not out_file.exists()

    # 4. Real HTTP request now immediately returns 503 fallback
    resp_after_kill = client.get("/api/auctions")
    assert resp_after_kill.status_code == 503
    assert resp_after_kill.json()["available"] is False


def test_real_os_separation_permissions(tmp_path, monkeypatch):
    from server.auction_snapshot import read_file
    transport_dir = tmp_path / "transport_isolated"
    transport_dir.mkdir(mode=0o750)
    test_file = transport_dir / "test.bin"
    test_file.write_bytes(b"hello 32-byte secret key 1234567")
    test_file.chmod(0o640)

    # 1. Same user or trusted UID with mode 0640 is valid
    data = read_file(str(test_file), 64)
    assert data == b"hello 32-byte secret key 1234567"

    # 2. Group write (0o660) must be rejected
    test_file.chmod(0o660)
    with pytest.raises(ValueError, match="Unsafe input"):
        read_file(str(test_file), 64)

    # 3. World read (0o644) must be rejected (no world access allowed)
    test_file.chmod(0o644)
    with pytest.raises(ValueError, match="Unsafe input"):
        read_file(str(test_file), 64)

    # 4. Group-writable directory must be rejected
    test_file.chmod(0o640)
    transport_dir.chmod(0o770)
    with pytest.raises(ValueError, match="Unsafe directory"):
        read_file(str(test_file), 64)


