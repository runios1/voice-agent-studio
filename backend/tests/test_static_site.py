"""mount_frontend: serves the built SPA same-origin without shadowing /api or /twilio."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.static_site import mount_frontend


def _build_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>BUILDER</html>")
    (dist / "dashboard.html").write_text("<html>DASHBOARD</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    return dist


def test_serves_shell_dashboard_and_assets_without_shadowing_api(tmp_path):
    dist = _build_dist(tmp_path)
    app = FastAPI()

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    assert mount_frontend(app, str(dist)) is True
    c = TestClient(app)

    assert "BUILDER" in c.get("/").text
    assert "DASHBOARD" in c.get("/dashboard").text
    assert c.get("/assets/app.js").status_code == 200
    # a deep client-side route falls back to the app shell
    assert "BUILDER" in c.get("/agents/xyz").text
    # real API routes still win; an unknown /api path is a real 404, not the shell
    assert c.get("/api/health").json() == {"ok": True}
    assert c.get("/api/does-not-exist").status_code == 404
    assert c.get("/twilio/media/x").status_code == 404


def test_noop_when_there_is_no_build(tmp_path):
    app = FastAPI()
    assert mount_frontend(app, str(tmp_path / "missing")) is False
    # nothing mounted -> root is a plain 404 (API-only mode, e.g. local dev / tests)
    assert TestClient(app).get("/").status_code == 404


def test_noop_when_not_explicitly_configured(monkeypatch):
    # No dist_dir arg and no FRONTEND_DIST env -> never serves, even if a stray
    # frontend/dist exists in the working tree (keeps local dev / CI API-only).
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    assert mount_frontend(FastAPI()) is False
