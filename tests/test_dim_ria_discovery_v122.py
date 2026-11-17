# -*- coding: utf-8 -*-
"""Official provider discovery must respect rights, quotas and privacy."""
import json
import sqlite3
import urllib.parse
from datetime import datetime, timezone

import pytest

from scripts.dim_ria_discovery import discover, db_connect, reserve_quota
from scripts.market_inventory import ingest

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
KEY = "A" * 40


def grant(path):
    path.write_text(json.dumps({
        "source_key": "dim_ria",
        "agreement_ref": "private_contract_ria",
        "operator_rights_reviewed": True,
        "metadata_display_permitted": True,
        "valid_until": "2027-12-31",
        "allowed_source_hosts": ["dom.ria.com"],
        "full_snapshot_allowed": False,
    }))
    return path


def execute(tmp_path, request, **kwargs):
    key = kwargs.pop("api_key", KEY)
    return discover(grant(tmp_path / "agreement.json"), tmp_path / "private.sqlite",
                    api_key=key, category=1, realty_type=2, operation_type=1,
                    state_id=10, city_id=10, pages=2, now=NOW,
                    request_fn=request, **kwargs)


def test_pagination_uses_only_official_endpoint_and_never_publishes(tmp_path):
    requests = []

    def request(url):
        requests.append(url)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        assert url.startswith("https://developers.ria.com/dom/search?")
        assert query["api_key"] == [KEY]
        assert query["state_id"] == ["10"]
        if query["page"] == ["0"]:
            return json.dumps({"items": [123, 456], "count": 3}).encode()
        return json.dumps({"items": [456, 789], "count": 3}).encode()

    outcome = execute(tmp_path, request)
    assert outcome == {"pages_requested":2,"ids_found":4,"new_ids":3,
                       "publications":0,"details_copied":0,"images_copied":0}
    with sqlite3.connect(tmp_path / "private.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM discovered_ids").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM quota").fetchone()[0] == 2
        cols = {x[1] for x in conn.execute("PRAGMA table_info(discovered_ids)")}
        assert {"phone", "images", "description", "owner", "address"}.isdisjoint(cols)


def test_explicit_rights_and_key_required(tmp_path):
    with pytest.raises(ValueError, match="API_KEY"):
        execute(tmp_path, lambda url: b'{"items":[1]}', api_key="")
    grant_file = grant(tmp_path / "a.json")
    bad = json.loads(grant_file.read_text())
    bad["operator_rights_reviewed"] = False
    grant_file.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="rights review"):
        discover(grant_file,tmp_path/"private.sqlite",api_key=KEY,category=1,
                 realty_type=2,operation_type=1,state_id=10,city_id=10,pages=1,
                 now=NOW,request_fn=lambda url: b'{"items":[1]}')


def test_no_call_after_local_hour_budget_is_exhausted(tmp_path):
    database = tmp_path / "private.sqlite"
    con = db_connect(database)
    for _ in range(30):
        reserve_quota(con, NOW)
    con.close()
    seen = []
    with pytest.raises(ValueError, match="budget exhausted"):
        execute(tmp_path, lambda url: seen.append(url) or b'{"items":[]}')
    assert seen == []


def test_bad_api_shape_consumes_reserved_budget_and_stays_private(tmp_path):
    with pytest.raises(ValueError, match="response shape"):
        execute(tmp_path, lambda url: b'{"unexpected":"no items"}')
    with sqlite3.connect(tmp_path / "private.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM quota").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM discovered_ids").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [0,-1,26,100])
def test_page_limit_prevents_quota_abuse(bad,tmp_path):
    with pytest.raises(ValueError, match="At most 25"):
        discover(grant(tmp_path/"a.json"),tmp_path/"private.sqlite",
                 api_key=KEY,category=1,realty_type=2,operation_type=1,
                 state_id=10,city_id=10,pages=bad,now=NOW,
                 request_fn=lambda url: b'{"items":[]}')
    assert not (tmp_path/"private.sqlite").exists()


def test_empty_page_ends_discovery_early(tmp_path):
    calls=[]
    def request(url):
        calls.append(1)
        return b'{"items":[], "count":0}'
    outcome=execute(tmp_path,request)
    assert outcome["pages_requested"]==1
    assert len(calls)==1
