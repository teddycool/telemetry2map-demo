from __future__ import annotations

import asyncio
import json

import pytest
import requests
import websockets


@pytest.mark.timeout(30)
def test_snapshot_then_live_update_and_stale_ignore(running_server):
    async def scenario() -> None:
        ws_events_url = running_server.replace("http", "ws") + "/ws/v1/events"
        ws_ingest_url = running_server.replace("http", "ws") + "/ws/v1/ingest"

        async with websockets.connect(ws_events_url, max_size=65536) as events_ws:
            snapshot = json.loads(await asyncio.wait_for(events_ws.recv(), timeout=3))
            assert snapshot["type"] == "snapshot"
            start_rev = snapshot["state"]["revision"]

            async with websockets.connect(ws_ingest_url, max_size=65536) as ingest_ws:
                payload = {
                    "type": "telemetry",
                    "version": 1,
                    "message_id": "m-1",
                    "entity_id": "entity-a",
                    "timestamp": "2026-10-23T12:34:56.123Z",
                    "position": {"latitude": 57.7201, "longitude": 16.9402},
                    "speed_kmh": 42.5,
                    "heading_deg": 125.0,
                    "info": ["Status: driving", "Load: test cargo"],
                }
                await ingest_ws.send(json.dumps(payload))
                ack = json.loads(await asyncio.wait_for(ingest_ws.recv(), timeout=3))
                assert ack["type"] == "ack"
                assert ack["status"] == "accepted"

                event = json.loads(await asyncio.wait_for(events_ws.recv(), timeout=3))
                assert event["type"] == "entity_updated"
                assert event["revision"] == start_rev + 1

                await ingest_ws.send(json.dumps(payload))
                stale = json.loads(await asyncio.wait_for(ingest_ws.recv(), timeout=3))
                assert stale["status"] == "ignored"

                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(events_ws.recv(), timeout=0.6)

    asyncio.run(scenario())


@pytest.mark.timeout(30)
def test_invalid_json_then_valid_message_connection_stays_open(running_server):
    async def scenario() -> None:
        ws_ingest_url = running_server.replace("http", "ws") + "/ws/v1/ingest"
        async with websockets.connect(ws_ingest_url, max_size=65536) as ingest_ws:
            await ingest_ws.send("{bad json")
            err = json.loads(await asyncio.wait_for(ingest_ws.recv(), timeout=3))
            assert err["type"] == "error"
            assert err["code"] == "invalid_json"

            payload = {
                "type": "telemetry",
                "version": 1,
                "message_id": "ok-1",
                "entity_id": "entity-b",
                "timestamp": "2026-10-23T12:35:56.123Z",
                "position": {"latitude": 57.7201, "longitude": 16.9402},
                "speed_kmh": 12.5,
                "heading_deg": 15.0,
                "info": ["ok"],
            }
            await ingest_ws.send(json.dumps(payload))
            ack = json.loads(await asyncio.wait_for(ingest_ws.recv(), timeout=3))
            assert ack["type"] == "ack"
            assert ack["status"] == "accepted"

    asyncio.run(scenario())


def test_http_settings_and_state(running_server):
    state = requests.get(running_server + "/api/v1/state", timeout=2)
    assert state.status_code == 200
    assert "settings" in state.json()

    response = requests.patch(
        running_server + "/api/v1/settings",
        json={"trace_mode": "samples", "trace_samples": 10, "trace_seconds": 10},
        timeout=2,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["trace_mode"] == "samples"
    assert body["trace_samples"] == 10

    bad = requests.patch(running_server + "/api/v1/settings", json={"unknown": 1}, timeout=2)
    assert bad.status_code == 400
