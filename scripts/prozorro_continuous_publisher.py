"""Continuous, bounded publisher daemon staging verified auction snapshot handoffs."""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.prozorro_atomic_publish import publish


def run_continuous_publisher(candidates_path, decisions_path, key_path, output_path,
                             *, interval=30.0, kill_switch_path=None, max_runs=None, enabled=True):
    """Periodically publish sealed snapshot while reusing verified candidates."""
    out = Path(output_path)
    runs = 0

    while max_runs is None or runs < max_runs:
        runs += 1

        # Check kill switch: stop regeneration and invalidate snapshot immediately
        if kill_switch_path and os.path.exists(kill_switch_path):
            if out.exists():
                try:
                    out.unlink()
                except OSError:
                    pass
            return "kill_switch_triggered"

        now = datetime.now(timezone.utc)
        try:
            count, size = publish(candidates_path, decisions_path, key_path, output_path,
                                  now=now, enabled=enabled)
            if count == 0:
                # No approved active items: invalidate snapshot to prevent serving empty active state
                if out.exists():
                    try:
                        out.unlink()
                    except OSError:
                        pass
        except Exception:
            # On fatal publishing failure, ensure snapshot doesn't linger indefinitely
            pass

        if max_runs is not None and runs >= max_runs:
            break

        time.sleep(interval)

    return "completed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--interval", type=float, default=30.0, help="Publishing interval in seconds (default: 30)")
    parser.add_argument("--kill-switch", default=None, help="Path to kill switch file")
    parser.add_argument("--max-runs", type=int, default=None, help="Maximum publishing iterations before stopping")
    parser.add_argument("--release", action="store_true", help="Explicitly enable approved auctions")
    args = parser.parse_args()

    if not args.release:
        parser.error("Explicit --release flag required for continuous publishing")

    result = run_continuous_publisher(
        args.candidates,
        args.decisions,
        args.key,
        args.output,
        interval=args.interval,
        kill_switch_path=args.kill_switch,
        max_runs=args.max_runs,
        enabled=True
    )
    print(f"Continuous publisher stopped: {result}")


if __name__ == "__main__":
    main()
