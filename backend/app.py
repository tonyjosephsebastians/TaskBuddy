from __future__ import annotations

import uuid

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from backend.agent.controller import AgentController
from backend.api.routes import router
from backend.config import API_PREFIX, APP_NAME, STATIC_DIR
from backend.errors import AppError
from backend.persistence.repository import TaskRepository


def create_app(repository: TaskRepository | None = None) -> FastAPI:
    repository = repository or TaskRepository()
    repository.initialize()
    controller = AgentController()

    app = FastAPI(title=APP_NAME)
    app.state.repository = repository
    app.state.controller = controller

    @app.middleware("http")
    async def add_trace_id(request: Request, call_next):
        request.state.trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "trace_id": getattr(request.state, "trace_id", str(uuid.uuid4())),
                "details": exc.details,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error_code": "REQUEST_VALIDATION_ERROR",
                "message": "Request body validation failed.",
                "trace_id": getattr(request.state, "trace_id", str(uuid.uuid4())),
                "details": {"errors": exc.errors()},
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router, prefix=API_PREFIX)

    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        index_path = STATIC_DIR / "index.html"
        requested_path = STATIC_DIR / full_path
        if full_path and requested_path.exists() and requested_path.is_file():
            return FileResponse(requested_path)
        if index_path.exists():
            return FileResponse(index_path)
        return PlainTextResponse("Frontend build not found. Run `npm run build` in the frontend directory.", status_code=503)

    return app


app = create_app()


def run() -> None:
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=False)
