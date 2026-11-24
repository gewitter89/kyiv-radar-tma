"""Operator-only staging export, stdout; never writes a public asset."""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from .prozorro_decision_ledger import approved_rows
from .prozorro_review_cache import review_candidates
from server.auction_snapshot import read_file, seal


def build(cache, decisions, key, *, now, enabled=False):
    rows = approved_rows(decisions, review_candidates(cache,now=now),
                         now=now,enabled=enabled)
    return seal(rows,key,now=now)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache",type=Path,required=True)
    parser.add_argument("--decisions",type=Path,required=True)
    parser.add_argument("--key",required=True)
    parser.add_argument("--staging-only",action="store_true")
    args=parser.parse_args()
    if not args.staging_only:
        parser.error("Explicit staging operator opt-in required")
    try:
        raw=build(args.cache,args.decisions,read_file(args.key,32),
                  now=datetime.now(timezone.utc),enabled=True)
        sys.stdout.buffer.write(raw)
    except Exception:
        parser.exit(1,"Staging export unavailable. No publication.\n")


if __name__=="__main__":
    main()
