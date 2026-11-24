"""No network; only synthetic responses for bounded probe."""
import json
from datetime import datetime, timedelta, timezone
import pytest
from scripts.prozorro_probe import probe, BASE, MAX_BYTES

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)


def test_fixed_origin_and_aggregate_only():
    seen = []
    def fetch(url):
        seen.append(url)
        return json.dumps([{"description": "PRIVATE"}]).encode()
    out = probe(since=NOW-timedelta(hours=1), now=NOW, request_fn=fetch)
    assert len(seen) == 1 and seen[0].startswith(BASE)
    assert seen[0].endswith("?limit=10")
    assert out == {"requests": 1, "procedures_seen": 1,
                   "unique_review_candidates": 0, "publications": 0,
                   "raw_records_saved": 0, "coverage_complete": False}


@pytest.mark.parametrize("raw", [b"{}", b"not-json", b"[1]", b"x"*(MAX_BYTES+1),
                                 b"[{}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}]"])
def test_unexpected_response_fails_closed(raw):
    with pytest.raises(ValueError):
        probe(since=NOW, now=NOW, request_fn=lambda _: raw)


@pytest.mark.parametrize("limit", [0, 11, True])
def test_bad_limit_never_requests(limit):
    with pytest.raises(ValueError):
        probe(since=NOW, now=NOW, limit=limit,
              request_fn=lambda _: pytest.fail("network call"))


def test_old_cursor_never_requests():
    with pytest.raises(ValueError):
        probe(since=NOW-timedelta(days=2), now=NOW,
              request_fn=lambda _: pytest.fail("network call"))
