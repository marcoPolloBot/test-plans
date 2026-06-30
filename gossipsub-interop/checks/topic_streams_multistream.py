#!/usr/bin/env python3
"""Verify a topic-streams run actually used multiple streams for multiple topics.

When the Topic Streams extension is negotiated, an implementation opens a
separate /gsts/v0beta stream per topic (per direction). The go interop node logs
periodic "Topic stream count" telemetry with the number of inbound/outbound
topic streams it has open to each peer (see startTopicStreamInspector in
go-libp2p/experiment.go).

The topic-streams scenario publishes on two topics, so a node forwarding both
topics to a mesh peer should have up to two concurrent outbound topic streams to
that peer. This check confirms that at least one node observed >= 2 concurrent
outbound topic streams to a single peer, i.e. distinct topics really were carried
on distinct streams rather than multiplexed onto the shared control stream.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate that a topic-streams Shadow run opened multiple concurrent "
            "topic streams (one per topic) to at least one peer."
        )
    )
    parser.add_argument(
        "shadow_output",
        help="Path to the Shadow output directory (the one containing the hosts/ folder).",
    )
    parser.add_argument(
        "--min-streams",
        type=int,
        default=2,
        help="Minimum concurrent outbound topic streams to a single peer that "
        "must be observed at least once (default: 2).",
    )
    return parser.parse_args()


def iter_stdout_logs(hosts_dir: Path):
    for stdout_file in sorted(hosts_dir.rglob("*.stdout")):
        if stdout_file.is_file():
            yield stdout_file


def main() -> int:
    args = parse_args()
    base_dir = Path(args.shadow_output).expanduser().resolve()
    hosts_dir = base_dir / "hosts"
    if not hosts_dir.is_dir():
        print(f"hosts directory not found under: {base_dir}", file=sys.stderr)
        return 1

    enabled_nodes = 0
    max_outbound = 0
    max_inbound = 0
    # nodes that saw >= min-streams concurrent outbound topic streams to a peer
    nodes_with_multistream: set[str] = set()

    for log_path in iter_stdout_logs(hosts_dir):
        node_name = log_path.parent.name
        with log_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                msg = entry.get("msg")
                if msg == "Topic Streams extension enabled":
                    enabled_nodes += 1
                elif msg == "Topic stream count":
                    out = int(entry.get("outbound_gsts_streams", 0))
                    inb = int(entry.get("inbound_gsts_streams", 0))
                    max_outbound = max(max_outbound, out)
                    max_inbound = max(max_inbound, inb)
                    if out >= args.min_streams:
                        nodes_with_multistream.add(node_name)

    print(f"Nodes that enabled Topic Streams: {enabled_nodes}")
    print(f"Max concurrent outbound topic streams to a single peer: {max_outbound}")
    print(f"Max concurrent inbound topic streams from a single peer: {max_inbound}")
    print(
        f"Nodes that observed >= {args.min_streams} concurrent outbound topic "
        f"streams to a peer: {len(nodes_with_multistream)}"
    )

    if enabled_nodes == 0:
        print(
            "FAILED: no node logged that the Topic Streams extension was enabled.",
            file=sys.stderr,
        )
        return 1

    if not nodes_with_multistream:
        print(
            f"FAILED: no node ever had >= {args.min_streams} concurrent outbound "
            "topic streams to a single peer; topics were not split across streams.",
            file=sys.stderr,
        )
        return 1

    print(
        f"PASSED: {len(nodes_with_multistream)} node(s) used >= {args.min_streams} "
        "concurrent topic streams to a single peer (multiple topics, multiple streams)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
