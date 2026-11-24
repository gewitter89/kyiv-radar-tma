# -*- coding: utf-8 -*-
"""P0 owner takedown: canonical SQLite status must override stale JSON."""
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import kyiv_radar_api as api
from server.owner_visibility import enforce_owner_submission_visibility


def owner(submission=5):
    return {
        "id": 101, "submission_id": submission,
        "source": "Київ Радар (Пряма заявка)",
        "moderationStatus": "approved",
        "title": "Синтетична квартира", "price": 14000,
        "actualityConfirmed": True, "reviewedByRadar": True,
    }


def partner():
    return {"id": 202, "source": "partner:agency", "price": 12000}


@pytest.fixture
def storage(tmp_path):
    database = tmp_path / "private.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute(
            "CREATE TABLE landlord_submissions (id INTEGER PRIMARY KEY, status TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO landlord_submissions VALUES (5, 'published')")
        conn.execute("INSERT INTO landlord_submissions VALUES (6, 'pending_review')")
        conn.execute("INSERT INTO landlord_submissions VALUES (7, 'withdrawn')")
    return database


def test_owner_requires_current_published_status(storage):
    sample = [owner(5), partner(), owner(6), owner(7), owner(999)]
    assert [r["id"] for r in enforce_owner_submission_visibility(sample, str(storage))] == [101, 202]
    with sqlite3.connect(storage) as conn:
        conn.execute("UPDATE landlord_submissions SET status='withdrawn' WHERE id=5")
    assert enforce_owner_submission_visibility(sample, str(storage)) == [partner()]
    with sqlite3.connect(storage) as conn:
        conn.execute("UPDATE landlord_submissions SET status='published' WHERE id=5")
    assert [r["id"] for r in enforce_owner_submission_visibility(sample, str(storage))] == [101, 202]


def test_all_db_failures_hide_owner_without_hiding_unrelated_rows(storage, tmp_path):
    sample = [owner(), partner()]
    assert enforce_owner_submission_visibility(sample, "") == [partner()]
    assert enforce_owner_submission_visibility(sample, str(tmp_path / "missing.sqlite")) == [partner()]
    corrupt = tmp_path / "invalid.sqlite"
    corrupt.write_bytes(b"not a sqlite db")
    assert enforce_owner_submission_visibility(sample, str(corrupt)) == [partner()]
    symlink = tmp_path / "symlink.sqlite"
    symlink.symlink_to(storage)
    assert enforce_owner_submission_visibility(sample, str(symlink)) == [partner()]
    assert enforce_owner_submission_visibility([partner()], "") == [partner()]


def test_source_mismatch_cannot_be_mistaken_for_owner(storage):
    fake_owner = dict(owner(), source="OLX")
    assert enforce_owner_submission_visibility([fake_owner], str(storage)) == [fake_owner]
    assert enforce_owner_submission_visibility([owner(True)], str(storage)) == []
    assert enforce_owner_submission_visibility([owner(-1)], str(storage)) == []


def test_stale_json_cannot_reach_public_deals_health_or_contact(
        storage, monkeypatch):
    synthetic = owner()
    monkeypatch.setattr(api, "DB_PATH", str(storage))
    monkeypatch.setattr(api, "load_trusted_deals", lambda: [synthetic])
    monkeypatch.setattr(api, "load_private_register", lambda *_: {})
    monkeypatch.setattr(api, "validate_telegram_init_data", lambda _d: {"id": 300})
    monkeypatch.setattr(api, "check_rate_limit", lambda *args, **kwargs: True)
    def should_not_run(*_a, **_kw):
        raise AssertionError("Closed owner listing must not expose private phone")
    monkeypatch.setattr(api, "get_private_contact", should_not_run)
    client = TestClient(api.app)

    initial = client.get("/api/deals")
    assert initial.status_code == 200
    assert [r["id"] for r in initial.json()["deals"]] == [101]
    assert client.get("/api/health").json()["deals_count"] == 1

    with sqlite3.connect(storage) as conn:
        conn.execute("UPDATE landlord_submissions SET status = 'withdrawn' WHERE id=5")
    after = client.get("/api/deals")
    assert after.status_code == 200
    assert after.json()["deals"] == []
    assert client.get("/api/health").json()["deals_count"] == 0

    response = client.post(
        "/api/send_contact", json={"dealId": 101, "initData": "synthetic"}
    )
    assert response.status_code == 404

    with sqlite3.connect(storage) as conn:
        conn.execute("DELETE FROM landlord_submissions WHERE id=5")
    assert client.get("/api/deals").json()["deals"] == []


def test_read_does_not_write_sqlite(storage):
    with sqlite3.connect(storage) as conn:
        before = conn.execute("PRAGMA data_version").fetchone()[0]
        assert conn.execute("SELECT COUNT(*) FROM landlord_submissions").fetchone()[0] == 3
    assert [r["id"] for r in enforce_owner_submission_visibility([owner()], str(storage))] == [101]
    with sqlite3.connect(storage) as conn:
        assert conn.execute("SELECT COUNT(*) FROM landlord_submissions").fetchone()[0] == 3
