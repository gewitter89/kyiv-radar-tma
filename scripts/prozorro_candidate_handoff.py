"""Pilot-account-only sanitized candidate handoff on stdout or atomic export file, never public."""
import argparse
import fcntl
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from .prozorro_review_cache import review_candidates
from .prozorro_review_projection import normalized_fields

ROOT = Path(__file__).resolve().parents[1]


def handoff(directory, *, now):
    result = []
    for row in review_candidates(directory, now=now):
        clean = normalized_fields(row)
        clean.update(observed_at=row["observed_at"], review_status="pending_review", publication_allowed=False)
        result.append(clean)
    return result


def export_handoff(collector_dir, destination_path, *, now=None, reader_gid=None):
    """Atomically export sanitized candidate rows from collector cache."""
    now = now or datetime.now(timezone.utc)
    rows = handoff(collector_dir, now=now)

    out = Path(destination_path)
    if not out.is_absolute():
        raise ValueError("Absolute canonical output path required")
    if out.is_symlink():
        raise ValueError("Output path cannot be a symlink")
    if out.resolve() != out:
        raise ValueError("Output path must be canonical without symlink ancestors")

    try:
        if out.is_relative_to(ROOT):
            raise ValueError("Output path cannot be inside repository")
    except ValueError as err:
        if "Output path cannot be inside repository" in str(err):
            raise

    parent = out.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("Target directory must exist and cannot be a symlink")

    parent_stat = parent.stat()
    if parent_stat.st_uid != os.geteuid() or (parent_stat.st_mode & 0o022) or (parent_stat.st_mode & 0o007):
        raise ValueError("Unsafe target directory permissions")

    payload = json.dumps(rows, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(payload) > 1024 * 1024:
        raise ValueError('Handoff exceeds bounded size')

    lock_path = parent / ".handoff.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    tmp_path_str = None
    try:
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or (info.st_mode & 0o077):
            raise ValueError("Unsafe handoff lock")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        fd, tmp_path_str = tempfile.mkstemp(dir=parent, prefix=".handoff-", suffix=".tmp")
        try:
            os.fchmod(fd, 0o640)
            target_gid = reader_gid if reader_gid is not None else os.getenv("KYIV_RADAR_REVIEWER_GID")
            if target_gid is not None:
                os.fchown(fd, -1, int(target_gid))

            with os.fdopen(fd, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_path_str, out)
            tmp_path_str = None

            dir_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if tmp_path_str and os.path.exists(tmp_path_str):
                try:
                    os.unlink(tmp_path_str)
                except OSError:
                    pass
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)

    return len(rows), len(payload)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--private-dir", type=Path, required=True)
    p.add_argument("--operator-handoff", action="store_true")
    p.add_argument("--export", type=Path, help="Atomically export sanitized candidates to destination file")
    args = p.parse_args()
    if not args.operator_handoff and not args.export:
        p.error("Explicit private handoff or export target required")

    now = datetime.now(timezone.utc)
    if args.export:
        try:
            count, size = export_handoff(args.private_dir, args.export, now=now)
            print(f"Exported {count} sanitized candidate(s) to {args.export} ({size} bytes)")
        except Exception as exc:
            p.exit(1, f"Private handoff export failed: {type(exc).__name__}\n")
    else:
        try:
            print(json.dumps(handoff(args.private_dir, now=now), ensure_ascii=True))
        except Exception:
            p.exit(1, "Private handoff failed. No publication.\n")


if __name__ == "__main__":
    main()
