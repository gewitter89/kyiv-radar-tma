"""Atomic, reviewer-authorized export of approved auction metadata to production/staging transport."""
import argparse
import fcntl
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .prozorro_decision_ledger import approved_rows
from .prozorro_moderation_cli import read_candidates
from server.auction_snapshot import read_file, seal, ROOT


def publish(candidates_path, decisions_path, key_path, output_path, *, now=None, enabled=False):
    """Publish HMAC-sealed snapshot atomically with directory serialization and fsync."""
    if not output_path or not os.path.isabs(output_path):
        raise ValueError("Absolute canonical output path required")

    out = Path(output_path)
    if os.path.islink(out):
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

    if out.exists():
        if os.path.islink(out):
            raise ValueError("Existing target cannot be a symlink")
        existing_stat = out.stat()
        if not stat.S_ISREG(existing_stat.st_mode):
            raise ValueError("Existing target must be a regular file")
        if existing_stat.st_nlink > 1:
            raise ValueError("Existing target cannot have hard links")

    explicit_now = now is not None

    # Acquire serialization lock on target directory
    lock_path = parent / ".publisher.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    tmp_path_str = None
    try:
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Unsafe publisher lock")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if os.path.lexists(parent / ".kill_switch"):
            raise ValueError("Auction release disabled")
        # Generate under lock so an older concurrent snapshot cannot overwrite a newer one.
        now = now if explicit_now else datetime.now(timezone.utc)
        candidates = read_candidates(candidates_path)
        key = read_file(key_path, 32)
        rows = approved_rows(Path(decisions_path), candidates, now=now, enabled=enabled)
        sealed = seal(rows, key, now=now)
        # Create unique temp file in the same directory using mkstemp
        fd, tmp_path_str = tempfile.mkstemp(dir=parent, prefix=".snapshot-", suffix=".tmp")
        try:
            # Set mode to 0o640 (owner rw, group r, world ---)
            os.fchmod(fd, 0o640)
            reader_gid = os.getenv("KYIV_RADAR_READER_GID")
            if reader_gid:
                os.fchown(fd, -1, int(reader_gid))
            with os.fdopen(fd, "wb") as f:
                f.write(sealed)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace; the API separately checks the same kill marker.
            if os.path.lexists(parent / ".kill_switch"):
                raise ValueError("Auction release disabled")
            os.replace(tmp_path_str, out)
            tmp_path_str = None

            # Directory fsync to commit directory entry to storage
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

    return len(rows), len(sealed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--release", action="store_true", help="Explicitly enable approved auctions")
    args = parser.parse_args()
    if not args.release:
        parser.error("Explicit --release flag required for atomic publishing")
    try:
        count, size = publish(args.candidates, args.decisions, args.key, args.output, enabled=True)
        print(f"Successfully published {count} approved auction(s) to {args.output} ({size} bytes)")
    except Exception as exc:
        parser.exit(1, f"Atomic publish failed: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
