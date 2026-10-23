from __future__ import annotations

import json
import math
import queue
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from dateutil.parser import isoparse

from .config import Defaults, Limits
from .timeutil import to_utc_z, utc_now

TRUCK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ValidationError(Exception):
    def __init__(self, code: str, message: str, message_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.message_id = message_id


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _require_keys(obj: dict[str, Any], allowed: set[str], required: set[str], path: str = "") -> None:
    unknown = set(obj.keys()) - allowed
    if unknown:
        raise ValidationError("invalid_payload", f"{path or 'payload'} has unknown field: {sorted(unknown)[0]}")
    missing = required - set(obj.keys())
    if missing:
        raise ValidationError("invalid_payload", f"{path or 'payload'} missing required field: {sorted(missing)[0]}")


def parse_rfc3339_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValidationError("invalid_payload", "timestamp must be an RFC3339 string")
    try:
        parsed = isoparse(value)
    except Exception as exc:
        raise ValidationError("invalid_payload", "timestamp must be a valid RFC3339 value") from exc
    if parsed.tzinfo is None:
        raise ValidationError("invalid_payload", "timestamp must include explicit UTC offset")
    return parsed.astimezone(timezone.utc)


def _validate_int(value: Any, name: str, min_value: int, max_value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("invalid_payload", f"{name} must be an integer")
    if value < min_value or value > max_value:
        raise ValidationError("invalid_payload", f"{name} must be between {min_value} and {max_value}")
    return value


@dataclass
class TracePoint:
    latitude: float
    longitude: float
    timestamp: datetime
    received_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timestamp": to_utc_z(self.timestamp),
            "received_at": to_utc_z(self.received_at),
        }


@dataclass
class TruckRecord:
    truck_id: str
    timestamp: datetime
    received_at: datetime
    latitude: float
    longitude: float
    speed_kmh: float
    heading_deg: float
    info: list[str]
    trace: list[TracePoint] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "truck_id": self.truck_id,
            "timestamp": to_utc_z(self.timestamp),
            "received_at": to_utc_z(self.received_at),
            "position": {"latitude": self.latitude, "longitude": self.longitude},
            "speed_kmh": self.speed_kmh,
            "heading_deg": self.heading_deg,
            "info": list(self.info),
            "trace": [point.to_dict() for point in self.trace],
        }


@dataclass
class Viewer:
    viewer_id: str
    out_queue: queue.Queue
    overflowed: bool = False


class AppState:
    def __init__(self, defaults: Defaults, limits: Limits, clock: Callable[[], datetime] = utc_now):
        self._defaults = defaults
        self._limits = limits
        self._clock = clock
        self._lock = threading.RLock()
        self._revision = 0
        self._instance_id = str(uuid.uuid4())
        self._settings = {
            "trace_mode": defaults.trace_mode,
            "trace_seconds": defaults.trace_seconds,
            "trace_samples": defaults.trace_samples,
            "stale_after_seconds": defaults.stale_after_seconds,
        }
        self._trucks: dict[str, TruckRecord] = {}
        self._viewers: dict[str, Viewer] = {}

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    @property
    def limits(self) -> Limits:
        return self._limits

    def now(self) -> datetime:
        return self._clock()

    def _trim_trace(self, truck: TruckRecord, now: datetime) -> bool:
        before = len(truck.trace)
        if self._settings["trace_mode"] == "seconds":
            cutoff = now - timedelta(seconds=self._settings["trace_seconds"])
            truck.trace = [p for p in truck.trace if p.received_at >= cutoff]
        else:
            truck.trace = truck.trace[-self._settings["trace_samples"] :]
        truck.trace = truck.trace[-self._limits.hard_trace_cap :]
        return len(truck.trace) != before

    def _prune_all_locked(self, now: datetime) -> bool:
        changed = False
        for truck in self._trucks.values():
            changed = self._trim_trace(truck, now) or changed
        return changed

    def _state_dict_locked(self, now: datetime) -> dict[str, Any]:
        return {
            "server_instance_id": self._instance_id,
            "revision": self._revision,
            "server_time": to_utc_z(now),
            "settings": dict(self._settings),
            "trucks": [truck.to_dict() for truck in sorted(self._trucks.values(), key=lambda t: t.truck_id)],
        }

    def settings_dict(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._settings)

    def prune_expired(self) -> dict[str, Any] | None:
        now = self._clock()
        with self._lock:
            if not self._prune_all_locked(now):
                return None
            self._revision += 1
            return {
                "type": "state_updated",
                "version": 1,
                "server_instance_id": self._instance_id,
                "revision": self._revision,
                "state": self._state_dict_locked(now),
            }

    def get_state(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            self._prune_all_locked(now)
            return self._state_dict_locked(now)

    def register_viewer(self, viewer: Viewer) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            self._prune_all_locked(now)
            self._viewers[viewer.viewer_id] = viewer
            snapshot = {"type": "snapshot", "version": 1, "state": self._state_dict_locked(now)}
            viewer.out_queue.put_nowait(snapshot)
            return snapshot

    def unregister_viewer(self, viewer_id: str) -> None:
        with self._lock:
            self._viewers.pop(viewer_id, None)

    def _broadcast_locked(self, event: dict[str, Any]) -> list[Viewer]:
        for viewer in list(self._viewers.values()):
            try:
                viewer.out_queue.put_nowait(event)
            except queue.Full:
                viewer.overflowed = True
        return list(self._viewers.values())

    def ingest_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        now = self._clock()
        parsed = self._validate_payload(payload)

        with self._lock:
            if parsed["truck_id"] not in self._trucks and len(self._trucks) >= self._limits.max_trucks:
                raise ValidationError("capacity_exceeded", "maximum number of trucks reached", parsed["message_id"])

            if parsed["timestamp"] > now + timedelta(seconds=self._limits.max_future_skew_seconds):
                raise ValidationError("future_timestamp", "timestamp is too far in the future", parsed["message_id"])

            truck = self._trucks.get(parsed["truck_id"])
            if truck and parsed["timestamp"] <= truck.timestamp:
                ack = {
                    "type": "ack",
                    "version": 1,
                    "message_id": parsed["message_id"],
                    "truck_id": parsed["truck_id"],
                    "status": "ignored",
                    "reason": "stale_timestamp",
                    "revision": self._revision,
                    "received_at": to_utc_z(now),
                }
                return ack, None

            new_truck = truck or TruckRecord(
                truck_id=parsed["truck_id"],
                timestamp=parsed["timestamp"],
                received_at=now,
                latitude=parsed["latitude"],
                longitude=parsed["longitude"],
                speed_kmh=parsed["speed_kmh"],
                heading_deg=parsed["heading_deg"],
                info=list(parsed["info"]),
            )

            new_truck.timestamp = parsed["timestamp"]
            new_truck.received_at = now
            new_truck.latitude = parsed["latitude"]
            new_truck.longitude = parsed["longitude"]
            new_truck.speed_kmh = parsed["speed_kmh"]
            new_truck.heading_deg = parsed["heading_deg"]
            new_truck.info = list(parsed["info"])
            new_truck.trace.append(
                TracePoint(
                    latitude=parsed["latitude"],
                    longitude=parsed["longitude"],
                    timestamp=parsed["timestamp"],
                    received_at=now,
                )
            )
            self._trim_trace(new_truck, now)
            self._trucks[parsed["truck_id"]] = new_truck
            self._revision += 1
            event = {
                "type": "truck_updated",
                "version": 1,
                "server_instance_id": self._instance_id,
                "revision": self._revision,
                "truck": new_truck.to_dict(),
            }
            ack = {
                "type": "ack",
                "version": 1,
                "message_id": parsed["message_id"],
                "truck_id": parsed["truck_id"],
                "status": "accepted",
                "revision": self._revision,
                "received_at": to_utc_z(now),
            }
            return ack, event

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValidationError("invalid_payload", "settings patch must be an object")
        if not patch:
            raise ValidationError("invalid_payload", "settings patch cannot be empty")
        allowed = {"trace_mode", "trace_seconds", "trace_samples"}
        unknown = set(patch.keys()) - allowed
        if unknown:
            raise ValidationError("invalid_payload", f"unknown settings field: {sorted(unknown)[0]}")

        updates: dict[str, Any] = {}
        if "trace_mode" in patch:
            mode = patch["trace_mode"]
            if mode not in {"seconds", "samples"}:
                raise ValidationError("invalid_payload", "trace_mode must be 'seconds' or 'samples'")
            updates["trace_mode"] = mode
        if "trace_seconds" in patch:
            updates["trace_seconds"] = _validate_int(patch["trace_seconds"], "trace_seconds", 1, self._limits.max_trace_seconds)
        if "trace_samples" in patch:
            updates["trace_samples"] = _validate_int(
                patch["trace_samples"], "trace_samples", 1, self._limits.max_trace_samples
            )

        now = self._clock()
        with self._lock:
            self._settings.update(updates)
            self._prune_all_locked(now)
            self._revision += 1
            return {
                "type": "state_updated",
                "version": 1,
                "server_instance_id": self._instance_id,
                "revision": self._revision,
                "state": self._state_dict_locked(now),
            }

    def broadcast_event(self, event: dict[str, Any]) -> list[Viewer]:
        with self._lock:
            return self._broadcast_locked(event)

    def _validate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValidationError("invalid_payload", "payload must be an object")

        _require_keys(
            payload,
            allowed={"type", "version", "message_id", "truck_id", "timestamp", "position", "speed_kmh", "heading_deg", "info"},
            required={"type", "version", "message_id", "truck_id", "timestamp", "position", "speed_kmh", "heading_deg", "info"},
        )

        if payload["type"] != "telemetry":
            raise ValidationError("unsupported_message", "unsupported message type", payload.get("message_id"))
        if payload["version"] != 1:
            raise ValidationError("unsupported_version", "unsupported version", payload.get("message_id"))

        message_id = payload["message_id"]
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValidationError("invalid_payload", "message_id must be a non-empty string")

        truck_id = payload["truck_id"]
        if not isinstance(truck_id, str) or len(truck_id) > self._limits.max_truck_id_chars or not TRUCK_ID_PATTERN.match(truck_id):
            raise ValidationError("invalid_payload", "truck_id format is invalid", message_id)

        timestamp = parse_rfc3339_utc(payload["timestamp"])

        position = payload["position"]
        if not isinstance(position, dict):
            raise ValidationError("invalid_payload", "position must be an object", message_id)
        _require_keys(position, allowed={"latitude", "longitude"}, required={"latitude", "longitude"}, path="position")
        lat = position["latitude"]
        lon = position["longitude"]
        if not _is_number(lat) or lat < -90 or lat > 90:
            raise ValidationError("invalid_payload", "position.latitude must be between -90 and 90", message_id)
        if not _is_number(lon) or lon < -180 or lon > 180:
            raise ValidationError("invalid_payload", "position.longitude must be between -180 and 180", message_id)

        speed_kmh = payload["speed_kmh"]
        heading_deg = payload["heading_deg"]
        if not _is_number(speed_kmh) or speed_kmh < 0:
            raise ValidationError("invalid_payload", "speed_kmh must be a finite nonnegative number", message_id)
        if not _is_number(heading_deg) or heading_deg < 0 or heading_deg >= 360:
            raise ValidationError("invalid_payload", "heading_deg must be in [0, 360)", message_id)

        info = payload["info"]
        if not isinstance(info, list):
            raise ValidationError("invalid_payload", "info must be an array", message_id)
        if len(info) > self._limits.max_info_strings:
            raise ValidationError("capacity_exceeded", "too many info strings", message_id)
        normalized_info: list[str] = []
        for entry in info:
            if not isinstance(entry, str):
                raise ValidationError("invalid_payload", "all info values must be strings", message_id)
            if len(entry) > self._limits.max_info_string_chars:
                raise ValidationError("capacity_exceeded", "info string exceeds maximum length", message_id)
            normalized_info.append(entry)

        return {
            "message_id": message_id,
            "truck_id": truck_id,
            "timestamp": timestamp,
            "latitude": float(lat),
            "longitude": float(lon),
            "speed_kmh": float(speed_kmh),
            "heading_deg": float(heading_deg),
            "info": normalized_info,
        }


def parse_json_message(message: str) -> dict[str, Any]:
    try:
        return json.loads(message)
    except json.JSONDecodeError as exc:
        raise ValidationError("invalid_json", "malformed JSON payload") from exc
