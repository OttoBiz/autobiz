from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.models import Business, BusinessPartner, Product, Transaction

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Modify this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers here later
# from .api.v1.endpoints import some_router
# app.include_router(some_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {"message": "Welcome to the Business API"}