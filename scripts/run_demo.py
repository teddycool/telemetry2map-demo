from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)


def _wait_for_health(health_url: str, timeout_seconds: int) -> None:
    start = time.time()
    while True:
        try:
            with urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    return
        except (URLError, OSError, TimeoutError, ConnectionError):
            pass

        if time.time() - start > timeout_seconds:
            raise TimeoutError(f"Timed out waiting for {health_url}")
        time.sleep(0.5)


def _compose_down(project_root: Path) -> None:
    subprocess.run(["docker", "compose", "down"], cwd=str(project_root), check=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start app + replay test-data in one command")
    parser.add_argument("--host", default="localhost", help="Host for browser and websocket URL")
    parser.add_argument("--port", type=int, default=8000, help="Published app port")
    parser.add_argument("--interval", type=float, default=10.0, help="Seconds between telemetry messages")
    parser.add_argument("--jsonl", default="test-data/borgholm-byxelkrok.jsonl", help="JSONL test-data file path")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of messages to send (0 = all)",
    )
    parser.add_argument(
        "--down-on-exit",
        action="store_true",
        help="Run docker compose down automatically after replay exits or Ctrl+C",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open browser",
    )
    parser.add_argument("--health-timeout", type=int, default=90, help="Seconds to wait for app health")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]

    if shutil.which("docker") is None:
        print("ERROR: docker command not found", file=sys.stderr)
        return 1

    app_url = f"http://{args.host}:{args.port}"
    health_url = f"{app_url}/healthz"
    ws_url = f"ws://{args.host}:{args.port}/ws/v1/ingest"
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    message_prefix = f"replay-car-01-{run_id}"

    print("[1/4] Starting app container (docker compose up -d app)...")
    _run(["docker", "compose", "up", "--build", "-d", "app"], cwd=project_root)

    try:
        print(f"[2/4] Waiting for app health at {health_url} ...")
        _wait_for_health(health_url, timeout_seconds=args.health_timeout)

        print(f"[3/4] App is healthy: {app_url}")
        if not args.no_browser:
            webbrowser.open(app_url, new=2)
            print("Opened browser.")

        replay_cmd = [
            sys.executable,
            "scripts/replay_testdata.py",
            "--jsonl",
            args.jsonl,
            "--ws-url",
            ws_url,
            "--interval",
            str(args.interval),
            "--message-prefix",
            message_prefix,
        ]
        if args.limit > 0:
            replay_cmd.extend(["--limit", str(args.limit)])

        print("[4/4] Replaying test-data. Press Ctrl+C to stop replay.")
        subprocess.run(replay_cmd, cwd=str(project_root), check=True)
        print("Replay completed.")
        print(f"Map still available at: {app_url}")
    except KeyboardInterrupt:
        print("Interrupted by user.")
    finally:
        if args.down_on_exit:
            print("Stopping containers (docker compose down)...")
            _compose_down(project_root)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())