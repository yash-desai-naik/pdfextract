"""Warmset Web App — FastAPI backend server.

Serves the React frontend, handles PDF→DXF conversion,
DXF geometry serving, and Warmset takeoff calculations.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import convert, dxf_api, takeoff

app = FastAPI(title="Warmset Web App", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(convert.router, prefix="/api")
app.include_router(dxf_api.router, prefix="/api")
app.include_router(takeoff.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# Serve React build in production
_frontend_build = Path(__file__).parent.parent / "app" / "dist"
if _frontend_build.exists():
    app.mount(
        "/", StaticFiles(directory=str(_frontend_build), html=True), name="frontend"
    )


def main():
    import uvicorn

    uvicorn.run("webapp.server:app", host="0.0.0.0", port=8520, reload=True)


if __name__ == "__main__":
    main()
