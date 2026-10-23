from __future__ import annotations

import atexit
import threading

from flask import Flask
from flask_sock import Sock

from .config import Defaults, Limits
from .http import bp as http_bp
from .state import AppState
from .ws import events_loop, ingest_loop


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")

    defaults = Defaults()
    limits = Limits()
    app.config["DEFAULTS"] = defaults
    app.config["LIMITS"] = limits
    app.config["SOCK_SERVER_OPTIONS"] = {"max_message_size": limits.max_message_bytes}

    app_state = AppState(defaults=defaults, limits=limits)
    app.config["APP_STATE"] = app_state

    app.register_blueprint(http_bp)

    sock = Sock(app)

    @sock.route("/ws/v1/ingest")
    def ws_ingest(ws):
        ingest_loop(ws, app_state)

    @sock.route("/ws/v1/events")
    def ws_events(ws):
        events_loop(ws, app_state)

    stop_event = threading.Event()

    def expiry_worker() -> None:
        while not stop_event.wait(timeout=defaults.expiry_interval_seconds):
            event = app_state.prune_expired()
            if event:
                app_state.broadcast_event(event)

    thread = threading.Thread(target=expiry_worker, daemon=True)
    thread.start()

    def _shutdown_worker() -> None:
        stop_event.set()

    atexit.register(_shutdown_worker)

    return app
