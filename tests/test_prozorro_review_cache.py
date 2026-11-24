import os
from datetime import datetime, timedelta, timezone

import pytest
from scripts.prozorro_review_cache import apply_page, review_candidates, ROOT
from test_prozorro_auction_candidates import payload

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
pytestmark = pytest.mark.skipif(os.name != "posix", reason="Private POSIX storage")


def row(minutes=0, **changes):
    p = payload()
    p["dateModified"] = (NOW+timedelta(minutes=minutes)).isoformat()
    p.update(changes)
    return p


def put(tmp_path, rows, now=NOW):
    tmp_path.chmod(0o700)
    return apply_page(tmp_path, rows, observed_at=now, now=now)


def test_cache_idempotent_and_no_raw_metadata(tmp_path):
    put(tmp_path, [row(), row()])
    records = review_candidates(tmp_path, now=NOW)
    assert len(records) == 1
    assert records[0]["publication_allowed"] is False
    assert "PRIVATE" not in repr(records)
    db = tmp_path/"auction-review.sqlite"
    assert db.stat().st_mode & 0o777 == 0o600
    assert b"PRIVATE" not in db.read_bytes()


def test_partial_page_not_withdrawal_and_stale_hidden(tmp_path):
    put(tmp_path, [row()])
    put(tmp_path, [])
    assert len(review_candidates(tmp_path, now=NOW)) == 1
    assert review_candidates(tmp_path, now=NOW+timedelta(hours=1, seconds=1)) == []


def test_closed_new_version_and_old_replay(tmp_path):
    put(tmp_path, [row()])
    later = NOW+timedelta(minutes=1)
    put(tmp_path, [row(1, status="complete")], later)
    put(tmp_path, [row()], later)
    assert review_candidates(tmp_path, now=later) == []


def test_same_version_conflict_stays_hidden(tmp_path):
    put(tmp_path, [row(), row(_protected=True), row()])
    assert review_candidates(tmp_path, now=NOW) == []


def test_malformed_page_cannot_commit_first_row(tmp_path):
    with pytest.raises(ValueError):
        put(tmp_path, [row(), row(dateModified="bad")])
    assert not (tmp_path/"auction-review.sqlite").exists()


def test_public_storage_rejected():
    with pytest.raises(ValueError):
        apply_page(ROOT, [], observed_at=NOW, now=NOW)


def test_world_readable_directory_rejected(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(ValueError):
        apply_page(tmp_path, [], observed_at=NOW, now=NOW)


def test_bid_deadline_hides_candidate(tmp_path):
    p = row(tenderPeriod={"startDate": "2026-11-23T00:00:00Z",
                          "endDate": (NOW+timedelta(minutes=1)).isoformat()})
    put(tmp_path, [p])
    assert review_candidates(tmp_path, now=NOW+timedelta(minutes=1)) == []
