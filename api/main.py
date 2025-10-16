"""FastAPI application for Autobiz customer service platform."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import webhooks
from db.connection import close_db_pool, get_db_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup: Initialize connections
    await get_db_pool()

    yield

    # Shutdown: Close connections
    await close_db_pool()


# Create FastAPI app
app = FastAPI(
    title="Autobiz",
    description="AI-powered customer service platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Autobiz API is running"}
