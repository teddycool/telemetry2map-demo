from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, render_template, request

from .state import ValidationError

bp = Blueprint("http", __name__)


@bp.after_app_request
def no_store_json(response: Response) -> Response:
    if response.mimetype == "application/json":
        response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/")
def index():
    defaults = current_app.config["DEFAULTS"]
    return render_template(
        "index.html",
        tile_url=defaults.tile_url,
        tile_attribution=defaults.tile_attribution,
        tile_max_zoom=defaults.tile_max_zoom,
    )


@bp.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@bp.get("/api/v1/state")
def get_state():
    app_state = current_app.config["APP_STATE"]
    event = app_state.prune_expired()
    if event:
        app_state.broadcast_event(event)
    return jsonify(app_state.get_state())


@bp.get("/api/v1/settings")
def get_settings():
    return jsonify(current_app.config["APP_STATE"].settings_dict())


@bp.patch("/api/v1/settings")
def patch_settings():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": {"code": "invalid_payload", "message": "request JSON body required"}}), 400
    app_state = current_app.config["APP_STATE"]
    try:
        event = app_state.update_settings(payload)
    except ValidationError as exc:
        return jsonify({"error": {"code": exc.code, "message": exc.message}}), 400
    app_state.broadcast_event(event)
    return jsonify(event["state"]["settings"])
