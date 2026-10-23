from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    max_message_bytes: int = int(os.getenv("MAX_MESSAGE_BYTES", "65536"))
    max_info_strings: int = int(os.getenv("MAX_INFO_STRINGS", "100"))
    max_info_string_chars: int = int(os.getenv("MAX_INFO_STRING_CHARS", "512"))
    max_entity_id_chars: int = int(os.getenv("MAX_ENTITY_ID_CHARS", "64"))
    max_future_skew_seconds: int = int(os.getenv("MAX_FUTURE_SKEW_SECONDS", "30"))
    max_entities: int = int(os.getenv("MAX_ENTITIES", "100"))
    hard_trace_cap: int = int(os.getenv("HARD_TRACE_CAP", "3600"))
    max_trace_seconds: int = int(os.getenv("MAX_TRACE_SECONDS", "86400"))
    max_trace_samples: int = int(os.getenv("MAX_TRACE_SAMPLES", "3600"))
    viewer_queue_size: int = int(os.getenv("VIEWER_QUEUE_SIZE", "128"))


@dataclass(frozen=True)
class Defaults:
    trace_mode: str = os.getenv("TRACE_MODE", "seconds")
    trace_seconds: int = int(os.getenv("TRACE_SECONDS", "300"))
    trace_samples: int = int(os.getenv("TRACE_SAMPLES", "300"))
    stale_after_seconds: int = int(os.getenv("STALE_AFTER_SECONDS", "15"))
    expiry_interval_seconds: float = float(os.getenv("EXPIRY_INTERVAL_SECONDS", "1.0"))
    tile_url: str = os.getenv("TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    tile_attribution: str = os.getenv(
        "TILE_ATTRIBUTION",
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    )
    tile_max_zoom: int = int(os.getenv("TILE_MAX_ZOOM", "19"))


@dataclass(frozen=True)
class Gunicorn:
    workers: int = int(os.getenv("GUNICORN_WORKERS", "1"))
    threads: int = int(os.getenv("GUNICORN_THREADS", "32"))
    bind: str = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
