import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from scripts.prozorro_review_sync import sync_once
from scripts.prozorro_review_cache import review_candidates
from test_prozorro_auction_candidates import payload

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
pytestmark = pytest.mark.skipif(os.name != "posix", reason="Private POSIX storage")


def row(**changes):
    p = payload()
    p["dateModified"] = (NOW-timedelta(minutes=1)).isoformat()
    p.update(changes)
    return p


def fetch(rows):
    return lambda _: json.dumps(rows).encode()


def test_network_to_private_cache(tmp_path):
    tmp_path.chmod(0o700)
    report = sync_once(tmp_path, now=NOW, request_fn=fetch([row()]))
    assert report["private_review_count"] == 1
    assert report["publications"] == 0
    assert report["raw_records_saved"] == 0
    assert report["coverage_complete"] is False
    assert review_candidates(tmp_path, now=NOW)[0]["publication_allowed"] is False


def test_bad_second_page_leaves_no_database(tmp_path):
    tmp_path.chmod(0o700)
    batches = iter([json.dumps([row()]*10).encode(), b"broken"])
    with pytest.raises(ValueError):
        sync_once(tmp_path, now=NOW, request_fn=lambda _: next(batches))
    assert not (tmp_path/"auction-review.sqlite").exists()


def test_rejected_first_then_active_same_version_stays_hidden(tmp_path):
    tmp_path.chmod(0o700)
    report = sync_once(tmp_path, now=NOW, request_fn=fetch([row(_protected=True), row()]))
    assert report["private_review_count"] == 0


def test_withdrawal_across_runs(tmp_path):
    tmp_path.chmod(0o700)
    sync_once(tmp_path, now=NOW, request_fn=fetch([row()]))
    later = NOW+timedelta(minutes=1)
    report = sync_once(tmp_path, now=later,
                       request_fn=fetch([row(status="complete", dateModified=NOW.isoformat())]))
    assert report["private_review_count"] == 0


def test_parallel_sync_refuses_before_request(tmp_path):
    from scripts.prozorro_review_sync import exclusive_sync
    tmp_path.chmod(0o700)
    with exclusive_sync(tmp_path):
        with pytest.raises(RuntimeError, match="Another"):
            sync_once(tmp_path, now=NOW, request_fn=lambda _: pytest.fail("network called"))
    assert sync_once(tmp_path, now=NOW, request_fn=fetch([]))["publications"] == 0


def test_lock_released_after_network_failure(tmp_path):
    tmp_path.chmod(0o700)
    with pytest.raises(ValueError):
        sync_once(tmp_path, now=NOW, request_fn=lambda _: b"broken")
    assert sync_once(tmp_path, now=NOW, request_fn=fetch([row()]))["private_review_count"] == 1


def test_invalid_directory_refuses_before_network(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError):
        sync_once(tmp_path, now=NOW, request_fn=lambda _: pytest.fail("network called"))


def test_row_cap_rolls_back_batch(tmp_path, monkeypatch):
    from scripts import prozorro_review_cache as cache
    tmp_path.chmod(0o700)
    monkeypatch.setattr(cache, "MAX_CACHE_ROWS", 1)
    sync_once(tmp_path, now=NOW, request_fn=fetch([row()]))
    with pytest.raises(ValueError, match="row limit"):
        sync_once(tmp_path, now=NOW, request_fn=fetch([
            row(auctionId="CSE001-UA-20261124-00001")]))
    records = review_candidates(tmp_path, now=NOW)
    assert len(records) == 1 and records[0]["auction_id"] == row()["auctionId"]


def test_retention_purges_expired_cache_on_next_success(tmp_path):
    import sqlite3
    tmp_path.chmod(0o700)
    sync_once(tmp_path, now=NOW, request_fn=fetch([row()]))
    later = NOW + timedelta(days=3)
    assert sync_once(tmp_path, now=later, request_fn=fetch([]))["private_review_count"] == 0
    with sqlite3.connect(tmp_path/"auction-review.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM auction_review").fetchone()[0] == 0
