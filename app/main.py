"""FastAPI entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.jobs_routes import router as jobs_router
from app.api.routes import router
from app.config import BASE_DIR, get_settings
from app.exceptions import AppError
from app.logging_config import setup_logging

settings = get_settings()
setup_logging(settings)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    logger.info("Starting YouTube-to-Shorts AI (env=%s, provider=%s)",
                settings.app_env, settings.ai_provider)
    yield
    logger.info("Shutting down")


app = FastAPI(title="YouTube-to-Shorts AI", version="0.1.0", lifespan=lifespan)

if settings.app_env == "development":
    # Permissive CORS for local development only (e.g. a frontend served from a different
    # port/origin). Tighten this to specific origins before hosting anywhere shared.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(router)
app.include_router(jobs_router)

_frontend_dir = BASE_DIR / "frontend"
if _frontend_dir.is_dir():
    app.mount("/app", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")

    @app.get("/", include_in_schema=False)
    def _root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/app/")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning("%s on %s: %s", type(exc).__name__, request.url.path, exc.message)
    return JSONResponse(status_code=exc.status_code,
                        content={"error": type(exc).__name__, "detail": exc.message})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500,
                        content={"error": "InternalServerError", "detail": "Something went wrong."})
