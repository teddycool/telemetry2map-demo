from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests


ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def running_server():
    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    command = [
        sys.executable,
        "-m",
        "gunicorn",
        "-w",
        "1",
        "--threads",
        "8",
        "-b",
        f"127.0.0.1:{port}",
        "app:app",
    ]
    proc = subprocess.Popen(command, cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    base_url = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            if requests.get(base_url + "/healthz", timeout=0.25).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.1)
    else:
        output = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""
        proc.kill()
        raise RuntimeError(f"Server did not start. Output:\n{output}")

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
