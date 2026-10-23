from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from map.config import Defaults, Limits
from map.state import AppState, ValidationError


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def payload(ts: str, entity_id: str = "entity-a", info: list[str] | None = None) -> dict:
    return {
        "type": "telemetry",
        "version": 1,
        "message_id": f"mid-{entity_id}-{ts}",
        "entity_id": entity_id,
        "timestamp": ts,
        "position": {"latitude": 57.72, "longitude": 16.94},
        "speed_kmh": 42.5,
        "heading_deg": 120.0,
        "info": info if info is not None else ["Status: driving"],
    }


def test_ingest_accepts_and_replaces_info_atomically() -> None:
    clock = Clock(datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc))
    state = AppState(defaults=Defaults(), limits=Limits(), clock=clock)

    ack1, event1 = state.ingest_payload(payload("2026-10-23T12:00:00Z", info=["A", "Unicode: åäö"]))
    assert ack1["status"] == "accepted"
    assert event1 is not None
    assert event1["entity"]["info"] == ["A", "Unicode: åäö"]

    clock.now += timedelta(seconds=1)
    ack2, event2 = state.ingest_payload(payload("2026-10-23T12:00:01Z", info=[]))
    assert ack2["status"] == "accepted"
    assert event2 is not None
    assert event2["entity"]["info"] == []


def test_stale_timestamp_ignored_without_mutation() -> None:
    clock = Clock(datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc))
    state = AppState(defaults=Defaults(), limits=Limits(), clock=clock)

    state.ingest_payload(payload("2026-10-23T12:00:01Z"))
    ack, event = state.ingest_payload(payload("2026-10-23T12:00:01Z"))
    assert ack["status"] == "ignored"
    assert ack["reason"] == "stale_timestamp"
    assert event is None


def test_rejects_future_timestamp() -> None:
    clock = Clock(datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc))
    state = AppState(defaults=Defaults(), limits=Limits(max_future_skew_seconds=10), clock=clock)

    with pytest.raises(ValidationError) as exc:
        state.ingest_payload(payload("2026-10-23T12:00:11Z"))
    assert exc.value.code == "future_timestamp"


def test_seconds_retention_prunes_on_background_tick() -> None:
    defaults = Defaults(trace_mode="seconds", trace_seconds=2)
    clock = Clock(datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc))
    state = AppState(defaults=defaults, limits=Limits(), clock=clock)

    state.ingest_payload(payload("2026-10-23T12:00:00Z"))
    clock.now += timedelta(seconds=1)
    state.ingest_payload(payload("2026-10-23T12:00:01Z"))
    clock.now += timedelta(seconds=3)
    event = state.prune_expired()

    assert event is not None
    entity = event["state"]["entities"][0]
    assert entity["trace"] == []
    assert entity["position"]["latitude"] == 57.72


def test_samples_retention_and_hard_cap() -> None:
    defaults = Defaults(trace_mode="samples", trace_samples=5)
    limits = Limits(hard_trace_cap=3)
    clock = Clock(datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc))
    state = AppState(defaults=defaults, limits=limits, clock=clock)

    for idx in range(6):
        ts = f"2026-10-23T12:00:0{idx}Z"
        state.ingest_payload(payload(ts))
        clock.now += timedelta(seconds=1)

    entity = state.get_state()["entities"][0]
    assert len(entity["trace"]) == 3


def test_max_entity_capacity() -> None:
    clock = Clock(datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc))
    limits = Limits(max_entities=1)
    state = AppState(defaults=Defaults(), limits=limits, clock=clock)

    state.ingest_payload(payload("2026-10-23T12:00:00Z", entity_id="entity-a"))
    with pytest.raises(ValidationError) as exc:
        state.ingest_payload(payload("2026-10-23T12:00:01Z", entity_id="entity-b"))
    assert exc.value.code == "capacity_exceeded"
