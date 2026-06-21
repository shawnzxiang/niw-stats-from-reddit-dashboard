"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from niw_stats.api.routes import router
from niw_stats.config import Settings, get_settings

# frontend/dist relative to the repo root (…/src/niw_stats/api/app.py -> up 4).
_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def create_app(settings: Settings | None = None, *, frontend_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="NIW Stats", version="0.1.0")
    app.state.settings = settings or get_settings()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(router)

    # Serve the built SPA last so it doesn't shadow /api routes.
    dist = Path(frontend_dist) if frontend_dist else _FRONTEND_DIST
    if dist.is_dir():
        index = dist / "index.html"

        # /debug is a client-side "route" that reveals the debug controls; there's no such
        # file on disk, so serve the SPA shell for it (matched before the "/" mount below).
        @app.get("/debug", include_in_schema=False)
        def _debug_route() -> FileResponse:
            return FileResponse(index)

        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app
