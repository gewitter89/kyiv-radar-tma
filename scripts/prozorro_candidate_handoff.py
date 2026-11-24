"""Pilot-account-only sanitized candidate handoff on stdout, never public."""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path
from .prozorro_review_cache import review_candidates
from .prozorro_review_projection import normalized_fields


def handoff(directory, *, now):
    result=[]
    for row in review_candidates(directory,now=now):
        clean=normalized_fields(row)
        clean.update(observed_at=row["observed_at"],review_status="pending_review",publication_allowed=False)
        result.append(clean)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--private-dir",type=Path,required=True)
    p.add_argument("--operator-handoff",action="store_true")
    args=p.parse_args()
    if not args.operator_handoff:
        p.error("Explicit private handoff required")
    try:
        print(json.dumps(handoff(args.private_dir,now=datetime.now(timezone.utc)),ensure_ascii=True))
    except Exception:
        p.exit(1,"Private handoff failed. No publication.\n")


if __name__=="__main__":
    main()
