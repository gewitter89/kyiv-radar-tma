# -*- coding: utf-8 -*-
"""Reviewer queue cannot publish or claim verification, and never copies PII."""
import json
import os
from pathlib import Path

import pytest

from scripts.reviewer_queue import build_review_queue, write_private_queue, CHECKS, ROOT


def record(listing_id: int, **extra):
    base = {
        "id": listing_id,
        "source": "OLX",
        "url": f"https://olx.ua/d/uk/offer-IDabc{listing_id}777.html",
        "images": [f"https://example.com/img{listing_id}.jpg"],
        "phone": "+380500000001",
        "ownerName": "PRIVATE NAME",
        "address": "PRIVATE ADDRESS",
        "desc": "PRIVATE DESCRIPTION",
    }
    base.update(extra)
    return base


def test_queue_prioritizes_source_duplicates_without_verifying_them():
    shared = "https://www.olx.ua/d/uk/offer-IDsame555.html?utm_source=share"
    other = "https://olx.ua/d/uk/offer-IDsame555.html"
    queue = build_review_queue([
        record(3),
        record(1, url=shared),
        record(2, url=other),
    ])
    assert queue["total_listings"] == 3
    assert queue["candidate_pair_count"] == 1
    assert [e["listing_id"] for e in queue["entries"]] == [1, 2, 3]
    first = queue["entries"][0]
    assert first["priority"] == "high_review"
    assert first["possible_duplicate_ids"] == [2]
    assert first["moderation_decision"] == "pending_manual_review"
    assert all(v == "not_reviewed" for v in first["checks"].values())
    assert set(first["checks"]) == set(CHECKS)
    assert queue["not_a_approval_or_publication_record"] is True


def test_queue_output_never_copies_private_source_fields():
    queue = build_review_queue([
        record(1, source="DOM.RIA", url="https://example.com/private?phone=111"),
        record(2, source="EXTRA +380987654321", title="A sensitive person's name"),
    ])
    output = json.dumps(queue, ensure_ascii=False)
    for forbidden in (
        "+380500000001", "+380987654321", "PRIVATE NAME",
        "PRIVATE ADDRESS", "PRIVATE DESCRIPTION", "sensitive", "example.com",
    ):
        assert forbidden not in output
    assert queue["entries"][1]["source"] == "OTHER"
    assert queue["entries"][1]["priority"] == "routine"


@pytest.mark.parametrize("invalid", [
    {}, None, "test", [None], [{"id": 0}], [{"id": True}],
    [{"id": 1}, {"id": 1}], [{"id": 1}, "not a row"],
])
def test_queue_rejects_malformed_catalog(invalid):
    with pytest.raises(ValueError):
        build_review_queue(invalid)


def test_queue_is_private_and_never_overwrites_existing_file(tmp_path):
    path = tmp_path / "review.json"
    queue = build_review_queue([record(1)])
    write_private_queue(queue, path)
    assert json.loads(path.read_text(encoding="utf-8")) == queue
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_private_queue(queue, path)


def test_queue_refuses_to_write_into_the_public_repo():
    queue = build_review_queue([record(1)])
    with pytest.raises(ValueError):
        write_private_queue(queue, ROOT / "data" / "must-not-create-review.json")


def test_queue_actual_catalog_keeps_150_unverified_records():
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "data" / "deals.json").read_text(encoding="utf-8"))
    queue = build_review_queue(catalog)
    assert queue["total_listings"] == 150
    assert len({entry["listing_id"] for entry in queue["entries"]}) == 150
    assert all(entry["moderation_decision"] == "pending_manual_review" for entry in queue["entries"])
