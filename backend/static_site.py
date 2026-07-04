"""Serve the built frontend from the FastAPI backend, so a production deploy is ONE
same-origin service: the API (`/api`), the live WS routes (`/api/.../preview/voice`,
`/twilio/media/...`), AND the static React app all answer on the same host. That is
exactly why the frontend can keep calling a relative `/api` and a same-host websocket
with no build-time URL config and no CORS.

No-op when there is no build present (`frontend/dist` absent) — local dev runs Vite
separately and tests never build — so calling this changes nothing there.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, dist_dir: str | None = None) -> bool:
    """Mount the built SPA. Returns True if a build was found and served, else False
    (API-only). Only activates when a dist is EXPLICITLY configured — `dist_dir` arg or
    the `FRONTEND_DIST` env var (the Dockerfile sets it) — so a stray local `dist/` or a
    CI checkout never silently turns on the catch-all. Call LAST in app assembly so every
    `/api` + WS route already registered takes precedence over the shell route."""
    configured = dist_dir or os.getenv("FRONTEND_DIST")
    if not configured:
        return False
    dist = Path(configured)
    index = dist / "index.html"
    if not index.exists():
        return False

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    dashboard = dist / "dashboard.html"

    @app.get("/dashboard", include_in_schema=False)
    @app.get("/dashboard.html", include_in_schema=False)
    async def _dashboard() -> FileResponse:
        return FileResponse(str(dashboard if dashboard.exists() else index))

    @app.get("/{path:path}", include_in_schema=False)
    async def _app_shell(path: str):
        # /api + /twilio are owned by earlier routes; never shadow them (an unmatched
        # one is a genuine 404, not the SPA shell). WS upgrades aren't GETs, so they're
        # untouched by this route regardless.
        if path.startswith("api/") or path.startswith("twilio/"):
            return Response(status_code=404)
        candidate = dist / path
        if path and candidate.is_file():
            return FileResponse(str(candidate))  # favicon, vite.svg, hashed files, ...
        return FileResponse(str(index))  # any client-side route -> the app shell

    return True
