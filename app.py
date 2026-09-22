from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Flask, Response, render_template, request, stream_with_context

from config import load_config
from monitor import Monitor

ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def _query_flag(req, name: str) -> bool:
    if name not in req.args:
        return False
    value = (req.args.get(name) or "").strip().lower()
    return value in ("", "1", "true", "yes", "on")


def create_app(config_path: str | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    config = load_config(config_path or os.environ.get("PRINTER_BUTLER_CONFIG"))
    monitor = Monitor(config, version=VERSION)
    monitor.start()
    app.config["MONITOR"] = monitor
    app.config["APP_CONFIG"] = config
    app.config["APP_VERSION"] = VERSION

    @app.context_processor
    def inject_version():
        return {"app_version": VERSION}

    @app.get("/")
    def index():
        snapshot = monitor.snapshot()
        return render_template(
            "index.html",
            snapshot=snapshot,
            start_fullscreen=_query_flag(request, "fullscreen"),
            start_autoscale=_query_flag(request, "autoscale"),
        )

    @app.get("/api/printers")
    def api_printers():
        return monitor.snapshot()

    @app.get("/api/stream")
    def api_stream():
        queue = monitor.subscribe()

        @stream_with_context
        def events():
            try:
                yield "retry: 5000\n\n"
                while True:
                    payload = queue.get()
                    if isinstance(payload, dict):
                        payload = json.dumps(payload, default=str)
                    yield f"data: {payload}\n\n"
            finally:
                monitor.unsubscribe(queue)

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "printers": len(config["printers"]), "version": VERSION}

    return app


app = create_app()


if __name__ == "__main__":
    listen = app.config["APP_CONFIG"]["listen"]
    app.run(host=listen.get("host", "0.0.0.0"), port=int(listen.get("port", 8080)), threaded=True)
