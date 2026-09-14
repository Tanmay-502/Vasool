import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, agents, cases, health, metrics, policy, webhooks


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Emit fail-safe configuration diagnostics once at application boot."""
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set — Gemini tier will fall through.")
    if not settings.GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not set — Groq tier will fall through.")
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        logger.warning("RAZORPAY_WEBHOOK_SECRET not set — signed recovery webhooks are disabled.")
    yield


app = FastAPI(
    title="Vasool",
    description="Explainable, policy-gated revenue recovery for failed payments",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(agents.router)
app.include_router(policy.router)
app.include_router(admin.router)
app.include_router(cases.router)
app.include_router(webhooks.router)
