from datetime import datetime, timedelta, timezone
import json
from urllib.parse import unquote

import pytest
from scripts.prozorro_incremental_scan import scan

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
START = NOW-timedelta(hours=1)


def row(minutes, key="CSE001-UA-20261124-00000"):
    return {"dateModified": (START+timedelta(minutes=minutes)).isoformat(),
            "auctionId": key, "description": "PRIVATE"}


def test_paging_preserves_boundary_and_never_claims_complete():
    calls = []
    batches = [[row(0), row(1)], [row(1), row(2)], [row(2)]]
    def fetch(url):
        calls.append(unquote(url))
        return json.dumps(batches.pop(0)).encode()
    report = scan(since=START, now=NOW, limit=2, request_fn=fetch)
    assert report == {"requests": 3, "procedures_seen": 5,
                      "unique_review_candidates": 0, "stop_reason": "short_page",
                      "coverage_complete": False, "publications": 0, "raw_records_saved": 0}
    assert "11:01:00.000000Z" in calls[1]


def test_equal_timestamp_stops_without_skipping_or_looping():
    calls = []
    def fetch(url):
        calls.append(url)
        return json.dumps([row(0), row(0)]).encode()
    report = scan(since=START, now=NOW, limit=2, request_fn=fetch)
    assert len(calls) == 1 and report["stop_reason"] == "cursor_stalled"


@pytest.mark.parametrize("rows", [[row(2), row(1)], [row(-1)], [{}], [row(100)]])
def test_bad_feed_is_not_accepted(rows):
    with pytest.raises(ValueError):
        scan(since=START, now=NOW, request_fn=lambda _: json.dumps(rows).encode())


@pytest.mark.parametrize("pages", [0, 4, True])
def test_invalid_budget_never_requests(pages):
    with pytest.raises(ValueError):
        scan(since=START, now=NOW, pages=pages,
             request_fn=lambda _: pytest.fail("unexpected request"))
