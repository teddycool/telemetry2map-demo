from __future__ import annotations

import asyncio
import json
import math
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone

import websockets


@dataclass
class SimConfig:
    ingest_url: str = os.getenv("SIM_INGEST_URL", "ws://app:8000/ws/v1/ingest")
    truck_count: int = int(os.getenv("SIM_TRUCK_COUNT", "3"))
    interval_seconds: float = float(os.getenv("SIM_INTERVAL_SECONDS", "1.0"))
    seed: int = int(os.getenv("SIM_SEED", "42"))


ROUTES = [
    [
        (57.7201, 16.9402),
        (57.7219, 16.9482),
        (57.7264, 16.9559),
        (57.7308, 16.9458),
        (57.7241, 16.9364),
        (57.7201, 16.9402),
    ],
    [
        (57.7050, 16.9428),
        (57.7093, 16.9601),
        (57.7008, 16.9747),
        (57.6922, 16.9612),
        (57.6975, 16.9465),
        (57.7050, 16.9428),
    ],
    [
        (57.7360, 16.9100),
        (57.7451, 16.9208),
        (57.7498, 16.9388),
        (57.7415, 16.9535),
        (57.7308, 16.9432),
        (57.7360, 16.9100),
    ],
]


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    d_lon = math.radians(lon2 - lon1)
    x = math.sin(d_lon) * math.cos(lat2_r)
    y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(d_lon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def _ts_utc_z() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def simulate_truck(config: SimConfig, truck_id: str, route: list[tuple[float, float]], jitter: random.Random) -> None:
    message_idx = 0
    point_idx = 0

    backoff = 1.0
    while True:
        try:
            async with websockets.connect(config.ingest_url, max_size=65536) as ws:
                backoff = 1.0
                while True:
                    a = route[point_idx % len(route)]
                    b = route[(point_idx + 1) % len(route)]
                    ratio = (message_idx % 6) / 6.0
                    lat = a[0] + (b[0] - a[0]) * ratio
                    lon = a[1] + (b[1] - a[1]) * ratio
                    heading = _bearing_deg(a[0], a[1], b[0], b[1])
                    speed = (_haversine_km(a[0], a[1], b[0], b[1]) * 3600.0 / max(config.interval_seconds * 6.0, 1e-6))
                    speed *= 1.0 + jitter.uniform(-0.03, 0.03)

                    payload = {
                        "type": "telemetry",
                        "version": 1,
                        "message_id": f"{truck_id}-{message_idx:06d}",
                        "truck_id": truck_id,
                        "timestamp": _ts_utc_z(),
                        "position": {"latitude": round(lat, 6), "longitude": round(lon, 6)},
                        "speed_kmh": round(speed, 2),
                        "heading_deg": round(heading, 2),
                        "info": [
                            f"Status: {'driving' if speed > 1 else 'idle'}",
                            f"Load: demo-{(message_idx // 8) % 5}",
                            f"Temperature: {17 + ((message_idx + point_idx) % 7)} °C",
                        ],
                    }
                    await ws.send(json.dumps(payload, ensure_ascii=False))
                    reply = await ws.recv()
                    try:
                        parsed = json.loads(reply)
                        print(f"[{truck_id}] {parsed.get('type')} {parsed.get('status', parsed.get('code'))}")
                    except json.JSONDecodeError:
                        print(f"[{truck_id}] non-json reply")

                    message_idx += 1
                    point_idx = point_idx + 1 if message_idx % 6 == 0 else point_idx
                    await asyncio.sleep(config.interval_seconds)
        except Exception as exc:
            print(f"[{truck_id}] disconnected: {exc}")
            await asyncio.sleep(backoff + jitter.uniform(0.0, 0.4))
            backoff = min(30.0, backoff * 2)


async def wait_for_app_health(base_http_url: str) -> None:
    import urllib.request

    health_url = base_http_url.rstrip("/") + "/healthz"
    backoff = 1.0
    while True:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        await asyncio.sleep(backoff)
        backoff = min(10.0, backoff * 1.5)


async def main() -> None:
    config = SimConfig()
    rng = random.Random(config.seed)

    base_http = os.getenv("SIM_HEALTH_BASE", "http://app:8000")
    await wait_for_app_health(base_http)

    tasks = []
    for idx in range(config.truck_count):
        route = ROUTES[idx % len(ROUTES)]
        truck_id = f"truck-{chr(ord('a') + idx)}"
        tasks.append(asyncio.create_task(simulate_truck(config, truck_id, route, random.Random(rng.randint(0, 1_000_000)))))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
