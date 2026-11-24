import json
import pytest
from scripts.prozorro_target_probe import inspect, BASE
from test_prozorro_auction_candidates import payload

PID = "a"*24
AID = "ALE001-UA-20261124-00000"


def test_schema_flags_without_private_fields():
    p = payload()
    p.update(auctionId=AID, sellingMethod="alienation-english")
    def request(url):
        assert url == BASE+PID
        return json.dumps(p).encode()
    result = inspect(procedure_id=PID, auction_id=AID, request_fn=request)
    assert result["identity_confirmed"] and result["ale_method"]
    assert result["cav_apartment"] and result["kyiv_locality"]
    assert not result["current_adapter_accepts"]
    assert result["publications"] == 0
    assert "PRIVATE" not in repr(result)


def test_identity_mismatch_is_rejected():
    with pytest.raises(ValueError):
        inspect(procedure_id=PID, auction_id=AID, request_fn=lambda _: b"{}")


def test_invalid_id_no_network():
    with pytest.raises(ValueError):
        inspect(procedure_id="../secret", auction_id=AID, request_fn=lambda _: pytest.fail("GET"))


def test_protected_record_never_inspected():
    out = inspect(procedure_id=PID, auction_id=AID,
                  request_fn=lambda _: json.dumps({"auctionId": AID, "_protected": True}).encode())
    assert out == {"protected_or_test": True, "publications": 0}
