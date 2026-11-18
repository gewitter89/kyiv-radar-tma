#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspect or explicitly repair the existing Kyiv Radar bot display name.

Does NOT change @username, Mini App title, token, menu URL, webhooks or service.
No token or token-bearing API URL is printed. Python standard library only.
Run only in a trusted environment already containing the existing bot token.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib import request

EXPECTED_HANDLE = "prostov_shrink_bot"
BRAND = "Київ Радар"
LANGUAGES = ("", "uk", "ru")
TOKEN_KEYS = ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN")


class BotIdentityError(RuntimeError):
    pass


def load_token(env_file=None):
    values = []
    for key in TOKEN_KEYS:
        value = os.environ.get(key, "").strip().strip('"').strip("'")
        if value:
            values.append(value)
    if env_file:
        path = Path(env_file)
        if not path.is_file():
            raise BotIdentityError("Specified environment file is unavailable")
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*(?:export\s+)?(TELEGRAM_BOT_TOKEN|BOT_TOKEN)\s*=\s*(.*?)\s*$", line)
            if not match:
                continue
            value = match.group(2).strip().strip('"').strip("'")
            if value and not value.startswith("#"):
                values.append(value)
    unique = set(values)
    if len(unique) != 1:
        raise BotIdentityError("Expected one existing token (missing or conflicting environment values)")
    token = unique.pop()
    if not re.fullmatch(r"[0-9]{6,}:[A-Za-z0-9_-]{20,}", token):
        raise BotIdentityError("Existing token has invalid format")
    return token


def call_api(token, method, payload=None):
    # Use POST for both reads and writes. Never log the token-bearing URL.
    url = "https://api.telegram.org/bot" + token + "/" + method
    data = json.dumps(payload or {}).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=12) as response:
            body = response.read(1048576)
        result = json.loads(body.decode("utf-8"))
    except Exception:
        raise BotIdentityError("Telegram API connection failed (details redacted)") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise BotIdentityError("Telegram API did not confirm this operation")
    return result.get("result")


def inspect(token):
    me = call_api(token, "getMe")
    if not isinstance(me, dict) or me.get("username", "").lower() != EXPECTED_HANDLE:
        raise BotIdentityError("Bot username mismatch; refusing to change a different bot")
    names = {}
    for lang in LANGUAGES:
        result = call_api(token, "getMyName", {"language_code": lang})
        if not isinstance(result, dict):
            raise BotIdentityError("Unexpected response when checking bot names")
        names[lang or "default"] = result.get("name", "")
    return names


def apply(token, names):
    for lang in LANGUAGES:
        key = lang or "default"
        if names[key] == BRAND:
            continue
        result = call_api(token, "setMyName", {"name": BRAND, "language_code": lang})
        if result is not True:
            raise BotIdentityError("Telegram did not confirm the name change")
    after = inspect(token)
    if not all(name == BRAND for name in after.values()):
        raise BotIdentityError("Name update not fully confirmed by Telegram")
    return after


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check or set existing Kyiv Radar Telegram bot display name")
    parser.add_argument("--env-file", default=None, help="Path to trusted existing .env; never pass token on CLI")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Read-only check (default recommended)")
    group.add_argument("--apply", action="store_true", help="Explicitly set display name for default/uk/ru")
    args = parser.parse_args(argv)
    try:
        token = load_token(args.env_file)
        names = inspect(token)
        print("Verified existing bot: @" + EXPECTED_HANDLE)
        for key, value in names.items():
            print(key + ": " + (value or "(unset)"))
        if args.apply:
            after = apply(token, names)
            print("Updated and verified display name: " + BRAND + " (" + ", ".join(after) + ")")
        else:
            print("Read-only; no changes made")
        print("Telegram native minimized tab and @username cannot be hidden by this script")
        return 0
    except BotIdentityError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
