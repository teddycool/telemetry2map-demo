from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import websockets


def utc_now_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def replay(
    jsonl_path: Path,
    ws_url: str,
    interval_seconds: float,
    message_prefix: str,
    keep_original_timestamps: bool,
    limit: int,
) -> None:
    lines = [line.strip() for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit > 0:
        lines = lines[:limit]
    total = len(lines)
    print(f"Loaded {total} messages from {jsonl_path}")
    print(f"Connecting to {ws_url}")

    async with websockets.connect(ws_url, max_size=65536) as ws:
        for idx, raw in enumerate(lines):
            payload = json.loads(raw)
            payload["message_id"] = f"{message_prefix}-{idx:06d}"
            if not keep_original_timestamps:
                payload["timestamp"] = utc_now_z()

            await ws.send(json.dumps(payload, ensure_ascii=False))
            reply_raw = await ws.recv()
            reply = json.loads(reply_raw)
            status = reply.get("status", reply.get("code", "unknown"))
            print(f"{idx + 1}/{total} -> {reply.get('type')} {status}")

            if idx < total - 1:
                await asyncio.sleep(interval_seconds)

    print("Replay complete")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay JSONL telemetry to ingest websocket")
    parser.add_argument(
        "--jsonl",
        default="test-data/borgholm-byxelkrok.jsonl",
        help="Path to JSONL file with one telemetry object per line",
    )
    parser.add_argument("--ws-url", default="ws://localhost:8000/ws/v1/ingest", help="Ingest websocket URL")
    parser.add_argument("--interval", type=float, default=10.0, help="Seconds between messages")
    parser.add_argument("--message-prefix", default="replay-entity-01", help="Prefix for generated message_id")
    parser.add_argument(
        "--keep-original-timestamps",
        action="store_true",
        help="Do not overwrite source timestamps (not recommended for live replay)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max messages to replay (0 = all)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(
        replay(
            jsonl_path=Path(args.jsonl),
            ws_url=args.ws_url,
            interval_seconds=args.interval,
            message_prefix=args.message_prefix,
            keep_original_timestamps=args.keep_original_timestamps,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
