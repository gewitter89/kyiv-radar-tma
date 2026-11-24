"""Operator CLI for isolated staging, with no remote endpoints or real grants by default."""
import argparse
import json
import os
from datetime import datetime,timezone
from pathlib import Path

from .prozorro_decision_ledger import record_rights, revoke_rights, decide, revoke_item
from .prozorro_auction_candidates import _utc
from .prozorro_review_projection import MAX_ITEMS
from server.auction_snapshot import read_file, MAX_BYTES


def read_candidates(path):
    owner = os.getenv('KYIV_RADAR_COLLECTOR_UID')
    rows=json.loads(read_file(path,MAX_BYTES,owner_uid=int(owner) if owner is not None else None))
    if not isinstance(rows,list) or len(rows)>MAX_ITEMS or any(not isinstance(r,dict) for r in rows):
        raise ValueError("Invalid candidate handoff")
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--decisions",type=Path,required=True)
    p.add_argument("--staging-only",action="store_true")
    sub=p.add_subparsers(dest="command",required=True)
    grant=sub.add_parser("grant-rights")
    grant.add_argument("--evidence-id",required=True)
    grant.add_argument("--until",required=True)
    grant.add_argument("--reviewed",action="store_true")
    sub.add_parser("revoke-rights")
    approve=sub.add_parser("approve")
    approve.add_argument("--candidates",required=True)
    approve.add_argument("--id",required=True)
    approve.add_argument("--until",required=True)
    approve.add_argument("--reviewed",action="store_true")
    deny=sub.add_parser("revoke-item")
    deny.add_argument("--id",required=True)
    args=p.parse_args()
    if not args.staging_only:
        p.error("Explicit staging operator opt-in required")
    now=datetime.now(timezone.utc)
    try:
        if args.command=="grant-rights":
            record_rights(args.decisions,evidence_id=args.evidence_id,valid_until=_utc(args.until),now=now,reviewed=args.reviewed)
        elif args.command=="revoke-rights":
            revoke_rights(args.decisions,now=now)
        elif args.command=="approve":
            rows=[r for r in read_candidates(args.candidates) if r.get("auction_id")==args.id]
            if len(rows)!=1:
                raise ValueError("Exactly one candidate required")
            decide(args.decisions,rows[0],now=now,valid_until=_utc(args.until),reviewed=args.reviewed)
        else:
            revoke_item(args.decisions,args.id,now=now)
    except Exception:
        p.exit(1,"Decision rejected; inspect private configuration.\n")
    print("Staging decision recorded; no publication.")


if __name__=="__main__":
    main()
