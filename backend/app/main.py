"""FixAI - On-Call AI Debugging Agent."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.api.organizations import router as org_router
from app.api.chat import router as chat_router

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown."""
    logger.info("starting_fixai", env=settings.app_env)
    if settings.app_env == "development":
        await init_db()
    yield
    logger.info("shutting_down_fixai")


app = FastAPI(
    title="FixAI",
    description="On-Call AI Debugging Agent",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- API routes ----------
app.include_router(org_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")


# ---------- Health ----------
@app.get("/health")
async def health():
    return {"status": "ok", "service": "fixai", "version": "0.1.0"}


# ---------- Static frontend (production) ----------
import pathlib

_frontend_dist = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
