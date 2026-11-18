# -*- coding: utf-8 -*-
"""Isolated tests. Never make network calls or use real Telegram tokens."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "telegram_branding", ROOT / "scripts" / "telegram_branding.py"
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)
TOKEN = "123456789:" + ("A" * 35)


def test_title_matches_original_short_brand():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "<title>Київ Радар</title>" in html
    assert "<title>Київ Радар —" not in html


def test_missing_token_fails_without_network():
    with patch.dict(mod.os.environ, {}, clear=True):
        with pytest.raises(mod.BotIdentityError):
            mod.load_token()


def test_mismatched_token_values_fails_closed():
    with patch.dict(mod.os.environ, {
        "BOT_TOKEN": TOKEN,
        "TELEGRAM_BOT_TOKEN": "123456789:" + ("B" * 35)
    }, clear=True):
        with pytest.raises(mod.BotIdentityError):
            mod.load_token()


def test_check_is_read_only_and_does_not_leak_token(capsys):
    def fake_call(token, method, payload=None):
        assert token == TOKEN
        if method == "getMe":
            return {"username": "prostov_shrink_bot"}
        if method == "getMyName":
            return {"name": "Old bot"}
        raise AssertionError("Unexpected write: " + method)

    with patch.object(mod, "load_token", return_value=TOKEN), patch.object(mod, "call_api", side_effect=fake_call):
        assert mod.main(["--check"]) == 0
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err
    assert "Read-only" in out.out


def test_apply_updates_only_names_and_checks_after(capsys):
    calls = []
    names = {"default": "Old bot", "uk": "Київ Радар", "ru": "Old bot"}
    def fake_call(token, method, payload=None):
        calls.append((method, payload))
        if method == "getMe":
            return {"username": "prostov_shrink_bot"}
        if method == "getMyName":
            return {"name": names[payload["language_code"] or "default"]}
        if method == "setMyName":
            assert payload["name"] == "Київ Радар"
            names[payload["language_code"] or "default"] = payload["name"]
            return True
        raise AssertionError(method)
    with patch.object(mod, "load_token", return_value=TOKEN), patch.object(mod, "call_api", side_effect=fake_call):
        assert mod.main(["--apply"]) == 0
    writes = [args for name, args in calls if name == "setMyName"]
    assert writes == [
        {"name": "Київ Радар", "language_code": ""},
        {"name": "Київ Радар", "language_code": "ru"}
    ]
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err
    assert "Updated and verified" in out.out


def test_refuses_wrong_bot():
    with patch.object(mod, "call_api", return_value={"username": "unrelated_bot"}):
        with pytest.raises(mod.BotIdentityError):
            mod.inspect(TOKEN)


def test_telegram_errors_redacted():
    with patch.object(mod.request, "urlopen", side_effect=RuntimeError("contains-secret-token")):
        with pytest.raises(mod.BotIdentityError) as exc:
            mod.call_api(TOKEN, "getMe")
        assert TOKEN not in str(exc.value)
        assert "contains-secret" not in str(exc.value)
