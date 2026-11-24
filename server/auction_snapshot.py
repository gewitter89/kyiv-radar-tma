"""Signed, short-lived read model for isolated auction staging; never raw SQLite."""
import hashlib
import hmac
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 1024 * 1024
MAX_ROWS = 2000
TTL = timedelta(seconds=60)
ID = re.compile(r"(?:ALE001|CSE001)-UA-[0-9]{8}-[0-9]{5}")
FIELDS = {"auction_id","source_url","kind","city","asset_class","starting_bid_uah",
          "vat_included","bidding_ends_at","source","observed_at","valid_until"}


def utc(value):
    dt = datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.utcoffset() is None:
        raise ValueError("Timezone required")
    return dt.astimezone(timezone.utc)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",",":"), allow_nan=False).encode()


def clean(rows, now):
    if not isinstance(rows,list) or len(rows)>MAX_ROWS:
        raise ValueError("Invalid rows")
    seen = set()
    out = []
    for row in rows:
        if not isinstance(row,dict) or set(row)!=FIELDS:
            raise ValueError("Unexpected fields")
        key = row["auction_id"]
        if not isinstance(key,str) or not ID.fullmatch(key) or key in seen:
            raise ValueError("Invalid identity")
        seen.add(key)
        if (row["source_url"] != "https://prozorro.sale/auction/"+key+"/"
            or row["source"]!="prozorro_sale" or row["kind"]!="sale_auction"
            or row["city"]!="Київ" or row["asset_class"]!="apartment_classified"
            or type(row["vat_included"]) is not bool):
            raise ValueError("Invalid metadata")
        raw = row["starting_bid_uah"]
        if not isinstance(raw,str) or len(raw)>24:
            raise ValueError("Invalid price")
        amount = Decimal(raw)
        if not amount.is_finite() or not 0<amount<=Decimal("1000000000000") or raw!=format(amount,".2f"):
            raise ValueError("Invalid price")
        observed,end,valid = [utc(row[k]) for k in ("observed_at","bidding_ends_at","valid_until")]
        if not observed<=now or valid>min(end,observed+timedelta(hours=1)):
            raise ValueError("Invalid validity")
        if now<valid and now<end:
            out.append(row)
    return out


def seal(rows, key, *, now):
    if not isinstance(key,bytes) or len(key)!=32:
        raise ValueError("32-byte staging key required")
    body = {"schema":1,"generated_at":now.isoformat(),"rows":clean(rows,now)}
    sig = hmac.new(key,canonical(body),hashlib.sha256).hexdigest()
    result = canonical({"body":body,"hmac":sig})
    if len(result)>MAX_BYTES:
        raise ValueError("Snapshot too large")
    return result


def unseal(raw,key,*,now):
    if len(raw)>MAX_BYTES or not isinstance(key,bytes) or len(key)!=32:
        raise ValueError("Invalid snapshot or key")
    envelope = json.loads(raw)
    if set(envelope)!={"body","hmac"} or not isinstance(envelope["hmac"],str):
        raise ValueError("Invalid envelope")
    body = envelope["body"]
    expected = hmac.new(key,canonical(body),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,envelope["hmac"]):
        raise ValueError("Invalid signature")
    if set(body)!={"schema","generated_at","rows"} or body["schema"]!=1:
        raise ValueError("Invalid schema")
    stamp = utc(body["generated_at"])
    if not timedelta(0)<=now-stamp<TTL:
        raise ValueError("Expired snapshot")
    # A copied response must also expire at the snapshot deadline.
    return [dict(row,valid_until=min(utc(row["valid_until"]),stamp+TTL).isoformat())
            for row in clean(body["rows"],now)]


def _trusted_publisher_uids():
    uids = {0, os.geteuid()}
    env_uid = os.getenv("KYIV_RADAR_PUBLISHER_UID")
    if env_uid:
        try:
            uids.add(int(env_uid))
        except ValueError:
            pass
    return uids


def read_file(value, limit, *, owner_uid=None):
    if not value:
        raise ValueError("Private path required")
    path = Path(value)
    if not path.is_absolute() or path.resolve()!=path or path.is_relative_to(ROOT):
        raise ValueError("Unsafe path")
    trusted_uids = _trusted_publisher_uids() if owner_uid is None else {owner_uid}
    parent = path.parent.stat()
    if (parent.st_mode & 0o022) or (parent.st_mode & 0o007) or parent.st_uid not in trusted_uids:
        raise ValueError("Unsafe directory")
    fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1
                or (info.st_mode & 0o027) or info.st_uid not in trusted_uids
                or info.st_size>limit):
            raise ValueError("Unsafe input")
        if info.st_uid != os.geteuid() and info.st_uid != 0:
            if not (info.st_mode & 0o040):
                raise ValueError("Group read required for distinct publisher")
            allowed_gids = {os.getegid()} | set(os.getgroups())
            if info.st_gid not in allowed_gids:
                raise ValueError("Reader group access required")
            if os.access(path, os.W_OK):
                raise ValueError("API process must have strictly read-only access")
        with os.fdopen(fd,"rb",closefd=False) as file:
            data = file.read(limit+1)
        if len(data)>limit:
            raise ValueError("Oversized input")
        return data
    finally:
        os.close(fd)


def load(snapshot_path,key_path,*,now):
    return unseal(read_file(snapshot_path,MAX_BYTES),read_file(key_path,32),now=now)
