"""Atomic, reviewer-authorized export of approved auction metadata to production/staging transport."""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from .prozorro_decision_ledger import approved_rows
from .prozorro_moderation_cli import read_candidates
from server.auction_snapshot import read_file, seal


def publish(candidates_path, decisions_path, key_path, output_path, *, now=None, enabled=True):
    now = now or datetime.now(timezone.utc)
    candidates = read_candidates(candidates_path)
    key = read_file(key_path, 32)
    rows = approved_rows(Path(decisions_path), candidates, now=now, enabled=enabled)
    sealed = seal(rows, key, now=now)

    out = Path(output_path).resolve()
    parent = out.parent
    if not parent.exists():
        parent.mkdir(mode=0o700, parents=True)

    tmp_path = out.with_suffix(out.suffix + ".tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(sealed)
        os.replace(tmp_path, out)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return len(rows), len(sealed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    if not args.release:
        parser.error("Explicit --release flag required for atomic publishing")
    try:
        count, size = publish(args.candidates, args.decisions, args.key, args.output)
        print(f"Successfully published {count} approved auction(s) to {args.output} ({size} bytes)")
    except Exception as exc:
        parser.exit(1, f"Atomic publish failed: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
