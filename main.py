from fastapi import FastAPI


app = FastAPI(
    title="WhatsApp AI Assistant",
    description="Modular, agent-based WhatsApp assistant for business automation",
    version="0.1.0",
)

@app.get("/")
async def root():
    """Root endpoint for basic health check."""
    return {"message": "WhatsApp AI Assistant is running"}
