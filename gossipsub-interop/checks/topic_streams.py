#!/usr/bin/env python3
"""Verify a topic-streams run delivered both blob and small messages everywhere.

The topic-streams scenario (see experiment.py) publishes large "blob" messages
and small, latency sensitive messages concurrently on two separate topics. Blob
messages use even message IDs and small messages use odd message IDs.

This check confirms that, regardless of whether the Topic Streams extension is
negotiated, every message of both classes still reaches every other node. It
reports the two classes separately so a regression on one topic (for example,
small messages starved behind blobs) is easy to spot.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that every blob and small message in a topic-streams "
            "Shadow run was delivered to all nodes."
        )
    )
    parser.add_argument(
        "shadow_output",
        help="Path to the Shadow output directory (the one containing the hosts/ folder).",
    )
    parser.add_argument(
        "--min-reach",
        type=float,
        default=1.0,
        help="Minimum fraction of non-publisher nodes that must receive each message (default: 1.0).",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=4,
        help="Number of initial (warmup) messages, per class, to skip when checking reach (default: 4).",
    )
    return parser.parse_args()


def iter_stdout_logs(hosts_dir: Path):
    """Yield all stdout log files under the given hosts directory."""
    for stdout_file in sorted(hosts_dir.rglob("*.stdout")):
        if stdout_file.is_file():
            yield stdout_file


def parse_logs(hosts_dir: Path):
    """Parse all stdout logs and return per-message delivery sets and node count."""
    deliveries: dict[str, set[str]] = defaultdict(set)
    first_seen: dict[str, str] = {}
    node_ids: set[str] = set()

    for log_path in iter_stdout_logs(hosts_dir):
        node_name = log_path.parent.name  # e.g. "node0"
        current_node_id: str | None = None

        with log_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                msg = entry.get("msg")
                if msg == "PeerID":
                    current_node_id = str(entry.get("node_id", node_name))
                    node_ids.add(current_node_id)
                elif msg == "Received Message":
                    mid = entry.get("id", "")
                    if not mid:
                        continue
                    nid = current_node_id or node_name
                    node_ids.add(nid)
                    deliveries[mid].add(nid)
                    ts = entry.get("time", "")
                    if mid not in first_seen or ts < first_seen[mid]:
                        first_seen[mid] = ts

    ordered_ids = sorted(deliveries.keys(), key=lambda m: first_seen.get(m, ""))
    return deliveries, ordered_ids, len(node_ids)


def check_class(
    label: str,
    ids: list[str],
    deliveries: dict[str, set[str]],
    expected_receivers: int,
    min_reach: float,
) -> int:
    """Print per-message reach for a class and return the number of failures."""
    print(f"{label}: {len(ids)} messages")
    failures = 0
    for mid in ids:
        receivers = len(deliveries[mid])
        reach = (
            min(receivers, expected_receivers) / expected_receivers
            if expected_receivers > 0
            else 0.0
        )
        status = "OK" if reach >= min_reach else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"  [{status}] {mid}: {receivers}/{expected_receivers} nodes ({reach:.0%})")
    print()
    return failures


def main() -> int:
    args = parse_args()
    base_dir = Path(args.shadow_output).expanduser().resolve()
    if not base_dir.exists():
        print(f"shadow output directory does not exist: {base_dir}", file=sys.stderr)
        return 1

    hosts_dir = base_dir / "hosts"
    if not hosts_dir.is_dir():
        print(f"hosts directory not found under: {base_dir}", file=sys.stderr)
        return 1

    deliveries, ordered_ids, node_count = parse_logs(hosts_dir)

    if not ordered_ids:
        print("no messages found in logs", file=sys.stderr)
        return 1

    if node_count == 0:
        print("no nodes found in logs", file=sys.stderr)
        return 1

    # Blob messages use even IDs, small messages use odd IDs.
    blob_ids = [m for m in ordered_ids if m.isdigit() and int(m) % 2 == 0]
    small_ids = [m for m in ordered_ids if m.isdigit() and int(m) % 2 == 1]

    # Skip warmup messages per class.
    blob_check = blob_ids[args.skip:]
    small_check = small_ids[args.skip:]

    if not blob_check and not small_check:
        print(
            f"no messages left after skipping {args.skip} warmup messages per class "
            f"(blob: {len(blob_ids)}, small: {len(small_ids)})",
            file=sys.stderr,
        )
        return 1

    expected_receivers = node_count - 1

    print(f"Nodes: {node_count}")
    print(f"Required reach: {args.min_reach:.0%}")
    print()

    failures = 0
    failures += check_class(
        "Blob messages", blob_check, deliveries, expected_receivers, args.min_reach
    )
    failures += check_class(
        "Small messages", small_check, deliveries, expected_receivers, args.min_reach
    )

    total = len(blob_check) + len(small_check)
    if failures:
        print(
            f"FAILED: {failures}/{total} messages did not reach "
            f"{args.min_reach:.0%} of nodes.",
            file=sys.stderr,
        )
        return 1

    print(f"PASSED: all {total} messages reached {args.min_reach:.0%} of nodes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
