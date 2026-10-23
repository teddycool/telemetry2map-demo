from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
import requests
import websockets


ROOT = Path(__file__).resolve().parents[2]


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f"
    b"\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\x0b\xe7\x02\x9d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def _send_telemetry(base_url: str, info: list[str]) -> None:
    ws_ingest_url = base_url.replace("http", "ws") + "/ws/v1/ingest"
    payload = {
        "type": "telemetry",
        "version": 1,
        "message_id": "browser-1",
        "entity_id": "entity-a",
        "timestamp": "2026-10-23T12:34:56.123Z",
        "position": {"latitude": 57.7201, "longitude": 16.9402},
        "speed_kmh": 42.5,
        "heading_deg": 125.0,
        "info": info,
    }
    async with websockets.connect(ws_ingest_url, max_size=65536) as ingest_ws:
        await ingest_ws.send(json.dumps(payload))
        await ingest_ws.recv()


@pytest.mark.timeout(60)
def test_info_box_replaces_and_renders_text_safely():
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "gunicorn", "-w", "1", "--threads", "8", "-b", f"127.0.0.1:{port}", "app:app"],
        cwd=str(ROOT),
        env=env,
    )
    base_url = f"http://127.0.0.1:{port}"

    try:
        for _ in range(100):
            try:
                if requests.get(base_url + "/healthz", timeout=0.2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("server failed to start")

        asyncio.run(_send_telemetry(base_url, ["Hello", "<script>alert(1)</script>"]))

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()

            page.route("**/tile.openstreetmap.org/**", lambda route: route.fulfill(status=200, body=PNG_1X1, headers={"content-type": "image/png"}))
            page.goto(base_url + "/", wait_until="domcontentloaded")

            page.wait_for_function("() => document.querySelector('#entity-select')?.options.length > 0")
            page.select_option("#entity-select", "entity-a")

            page.wait_for_timeout(1200)
            text = page.locator("#info-box").inner_text()
            assert "Hello" in text
            assert "<script>alert(1)</script>" in text

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
