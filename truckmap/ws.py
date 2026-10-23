from __future__ import annotations

import json
import queue
import threading
import uuid
from datetime import datetime
from typing import Any

from simple_websocket import ConnectionClosed

from .state import AppState, ValidationError, Viewer, parse_json_message
from .timeutil import to_utc_z


def _error(code: str, message: str, message_id: str | None = None) -> dict[str, Any]:
    return {
        "type": "error",
        "version": 1,
        "message_id": message_id,
        "code": code,
        "message": message,
    }


def _pong(now: datetime) -> dict[str, Any]:
    return {"type": "pong", "version": 1, "server_time": to_utc_z(now)}


def _send_json(ws, payload: dict[str, Any]) -> None:
    ws.send(json.dumps(payload, ensure_ascii=False))


def _handle_ping(obj: dict[str, Any]) -> bool:
    return isinstance(obj, dict) and obj.get("type") == "ping" and obj.get("version") == 1 and len(obj) == 2


def _viewer_writer(ws, viewer: Viewer, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        if viewer.overflowed:
            try:
                ws.close(1013, "viewer queue overflow")
            except Exception:
                pass
            break
        try:
            item = viewer.out_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        if item is None:
            break
        try:
            _send_json(ws, item)
        except Exception:
            break


def ingest_loop(ws, app_state: AppState) -> None:
    while True:
        try:
            raw = ws.receive()
        except ConnectionClosed:
            return

        if raw is None:
            return
        if isinstance(raw, bytes):
            ws.close(1003, "binary websocket frames are unsupported")
            return

        try:
            payload = parse_json_message(raw)
        except ValidationError as exc:
            _send_json(ws, _error(exc.code, exc.message, exc.message_id))
            continue

        if _handle_ping(payload):
            _send_json(ws, _pong(app_state.now()))
            continue

        try:
            ack, event = app_state.ingest_payload(payload)
        except ValidationError as exc:
            _send_json(ws, _error(exc.code, exc.message, exc.message_id))
            continue

        _send_json(ws, ack)
        if event:
            app_state.broadcast_event(event)


def events_loop(ws, app_state: AppState) -> None:
    viewer = Viewer(viewer_id=str(uuid.uuid4()), out_queue=queue.Queue(maxsize=app_state.limits.viewer_queue_size))
    stop_event = threading.Event()
    app_state.register_viewer(viewer)
    writer = threading.Thread(target=_viewer_writer, args=(ws, viewer, stop_event), daemon=True)
    writer.start()

    try:
        while True:
            try:
                raw = ws.receive()
            except ConnectionClosed:
                break
            if raw is None:
                break
            if isinstance(raw, bytes):
                ws.close(1003, "binary websocket frames are unsupported")
                break
            try:
                payload = parse_json_message(raw)
            except ValidationError as exc:
                _send_json(ws, _error(exc.code, exc.message, None))
                continue
            if _handle_ping(payload):
                _send_json(ws, _pong(app_state.now()))
            else:
                _send_json(ws, _error("unsupported_message", "events socket is read-only", None))
    finally:
        stop_event.set()
        try:
            viewer.out_queue.put_nowait(None)
        except queue.Full:
            pass
        app_state.unregister_viewer(viewer.viewer_id)
