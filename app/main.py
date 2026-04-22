"""
Main FastAPI application for Ottobiz
"""
import asyncio
import logging
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routers import analytics, inventory, supply_chain
from backend.api.routers.webhooks import whatsapp as whatsapp_webhook
from backend.chatbot.sweeper import sweep_loop

load_dotenv()

# Import database connection for lifecycle management
try:
    from backend.db.connection import close_db, init_db
    from backend.db.populate import populate_db_on_startup
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    populate_db_on_startup = None
    print("Warning: Database connection module not available")

LOG_FILE = os.getenv("LOG_FILE", "app.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s]: %(message)s'
)

# Create FastAPI app
app = FastAPI(
    title="Ottobiz API",
    description="Automated Business Platform API",
    version="1.0.0"
)

_sweeper_task: asyncio.Task | None = None

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database lifecycle events
@app.on_event("startup")
async def startup_event():
    """Initialize database connection pool and populate on startup"""
    global _sweeper_task

    if not DB_AVAILABLE:
        logging.warning("Database connection not available - running without database")
        print("⚠ Database connection not available - running without database")
        return

    for attempt in range(10):
        try:
            await init_db()
            logging.info("✓ Database connection pool initialized")
            print("✓ Database connection pool initialized")
            if populate_db_on_startup:
                await populate_db_on_startup()
                print("✓ Database populated with migrations and dummy data")
            break
        except Exception as e:
            logging.warning(f"DB init attempt {attempt + 1}/10 failed: {e}")
            if attempt < 9:
                await asyncio.sleep(3)
            else:
                logging.error(f"✗ Failed to initialize database: {e}")
                print(f"✗ Failed to initialize database: {e}")
                raise

    _sweeper_task = asyncio.create_task(sweep_loop())
    logging.info("✓ Outbound timeout sweeper started")


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection pool on shutdown"""
    global _sweeper_task

    if _sweeper_task is not None:
        _sweeper_task.cancel()
        try:
            await _sweeper_task
        except asyncio.CancelledError:
            pass
        _sweeper_task = None
        logging.info("✓ Outbound timeout sweeper stopped")

    if DB_AVAILABLE:
        try:
            await close_db()
            logging.info("✓ Database connection pool closed")
            print("✓ Database connection pool closed")
        except Exception as e:
            logging.error(f"✗ Failed to close database: {e}")
            print(f"✗ Failed to close database: {e}")

# Include routers
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(inventory.router, prefix="/api/v1")
app.include_router(supply_chain.router, prefix="/api/v1")
app.include_router(whatsapp_webhook.router)

# Mount static files for uploads
if os.path.exists("uploads"):
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "Ottobiz API",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "service": "Ottobiz API",
        "version": "1.0.0",
        "endpoints": {
            "analytics": "/api/v1/analytics",
            "inventory": "/api/v1/inventory",
            "supply_chain": "/api/v1/supply-chain",
            "whatsapp_webhook": "/webhooks/whatsapp",
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
