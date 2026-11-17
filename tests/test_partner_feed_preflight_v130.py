# -*- coding: utf-8 -*-
"""An agency snapshot must be inspected without touching any private DB."""
import csv
import json
from datetime import datetime, timezone

import pytest

from scripts.partner_feed_preflight import preflight, main

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def grant(tmp_path, **updates):
    obj = {
        "source_key": "partner_kyiv_pilot", "agreement_ref": "pilot_contract_1",
        "operator_rights_reviewed": True, "metadata_display_permitted": True,
        "valid_until": "2027-04-01", "allowed_source_hosts": ["partner.example.ua"],
        "full_snapshot_allowed": False,
    }
    obj.update(updates)
    path = tmp_path / "private-contract.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def listing(n, **kwargs):
    return {
        "external_id": str(n), "source_url": f"https://partner.example.ua/offer/{n}",
        "operation": "rent", "property_type": "apartment", "city": "Київ",
        "district": "Дарницький", "price_uah": 15000, "rooms": 2, "area_m2": 54,
        "ownerName": "PRIVATE OWNER", "phone": "+380501112233",
        "images": ["https://partner.example.ua/private.jpg"], **kwargs,
    }


def write_jsonl(tmp_path, rows):
    path = tmp_path / "feed.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return path


def test_preflight_is_read_only_and_does_not_return_contacts(tmp_path):
    feed = write_jsonl(tmp_path, [listing(1), listing(2)])
    approval = grant(tmp_path)
    before = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    result = preflight(feed, approval, now=NOW)
    after = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    assert result["ok"] and result["records_checked"] == 2
    assert result["publications"] == result["private_database_writes"] == 0
    assert result["requires_contract_and_reviewer_checks"] is True
    assert before == after
    assert "PRIVATE OWNER" not in json.dumps(result)
    assert "+380501112233" not in json.dumps(result)


def test_duplicate_ids_rejected_without_writes(tmp_path):
    feed = write_jsonl(tmp_path, [listing(1), listing(1)])
    with pytest.raises(ValueError, match="Duplicate"):
        preflight(feed, grant(tmp_path), now=NOW)
    assert not list(tmp_path.glob("*.db"))


def test_canonical_duplicate_urls_flagged_not_merged(tmp_path):
    feed = write_jsonl(tmp_path, [listing(1), listing(2,
        source_url="https://partner.example.ua/offer/1?utm_source=pilot")])
    result = preflight(feed, grant(tmp_path), now=NOW)
    assert result["duplicate_url_candidates"] == 1


@pytest.mark.parametrize("row", [
    listing(1, price_uah="15 000"),
    listing(1, source_url="http://partner.example.ua/offer/1"),
    listing(1, source_url="https://partner.example.ua.attacker.org/offer/1"),
    listing(1, operation="invented"),
])
def test_rejects_invalid_metadata(tmp_path, row):
    feed = write_jsonl(tmp_path, [row])
    with pytest.raises(ValueError):
        preflight(feed, grant(tmp_path), now=NOW)


def test_expired_or_unreviewed_grant_blocked(tmp_path):
    feed = write_jsonl(tmp_path, [listing(1)])
    with pytest.raises(ValueError):
        preflight(feed, grant(tmp_path, valid_until="2026-01-01"), now=NOW)
    with pytest.raises(ValueError):
        preflight(feed, grant(tmp_path, operator_rights_reviewed=False), now=NOW)


def test_empty_feed_rejected(tmp_path):
    feed = write_jsonl(tmp_path, [])
    with pytest.raises(ValueError, match="Empty"):
        preflight(feed, grant(tmp_path), now=NOW)


def test_csv_support(tmp_path):
    feed = tmp_path / "feed.csv"
    with feed.open("w", newline="", encoding="utf-8") as file:
        fields = ["external_id", "source_url", "operation", "property_type",
                  "city", "district", "price_uah", "rooms", "area_m2"]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerow({k: v for k, v in listing(1).items() if k in fields})
    assert preflight(feed, grant(tmp_path), now=NOW)["records_checked"] == 1


def test_cli_redacts_private_fields_on_failure(tmp_path, capsys):
    feed = write_jsonl(tmp_path, [listing(1, source_url="http://private-owner.test/")])
    rc = main(["--feed", str(feed), "--agreement", str(grant(tmp_path))])
    result = capsys.readouterr().out
    assert rc == 2
    assert "PRIVATE OWNER" not in result and "private-owner.test" not in result
    assert "partner.example.ua" not in result
    assert json.loads(result)["private_database_writes"] == 0


def test_unsupported_format_rejected(tmp_path):
    feed = write_jsonl(tmp_path, [listing(1)])
    with pytest.raises(ValueError):
        preflight(feed, grant(tmp_path), now=NOW, feed_format="other")


def test_cli_redacts_unexpected_parser_error(tmp_path, capsys, monkeypatch):
    from scripts import partner_feed_preflight as module

    def broken_parser(*args, **kwargs):
        raise RuntimeError("PRIVATE_OWNER: +380501112233 /secure/contract.json")

    monkeypatch.setattr(module, "preflight", broken_parser)
    rc = module.main(["--feed", str(tmp_path / "unreadable.csv"),
                      "--agreement", str(tmp_path / "grant.json")])
    output = capsys.readouterr().out
    assert rc == 2
    assert "PRIVATE_OWNER" not in output
    assert "+380501112233" not in output
    assert "/secure/contract.json" not in output
    assert json.loads(output)["error_type"] == "RuntimeError"
