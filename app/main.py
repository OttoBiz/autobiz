"""
Main FastAPI application for Ottobiz
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import logging
import os

# Import routers
from backend.api.routers import customer, business, logistics, analytics, inventory, supply_chain
from backend.whatsapp.routers import router as whatsapp_router

# Import legacy endpoints for backward compatibility
from backend.chatbot.agents.user_chat_interface import chat
from backend.chatbot.agents.business_chat_interface import business_chat
from backend.struct import UserRequest, BusinessRequest

load_dotenv()

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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(customer.router, prefix="/api/v1")
app.include_router(business.router, prefix="/api/v1")
app.include_router(logistics.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
app.include_router(inventory.router, prefix="/api/v1")
app.include_router(supply_chain.router, prefix="/api/v1")
app.include_router(whatsapp_router, prefix="/whatsapp")

# Legacy endpoints for backward compatibility
@app.post("/chat")
async def get_chat_response(user_request: UserRequest):
    """Legacy customer chat endpoint"""
    response = await chat(user_request, None)
    return {"message": response}


@app.post("/business_chat")
async def get_business_response(business_request: BusinessRequest):
    """Legacy business chat endpoint"""
    response = await business_chat(business_request, None)
    return {"message": response}


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
            "customer": "/api/v1/customer",
            "business": "/api/v1/business",
            "logistics": "/api/v1/logistics",
            "analytics": "/api/v1/analytics",
            "inventory": "/api/v1/inventory",
            "supply_chain": "/api/v1/supply-chain"
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
