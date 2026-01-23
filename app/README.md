# Ottobiz Backend

Backend API for the Ottobiz automated business platform.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables in `.env`:
```env
MODEL_NAME=gemini-2.0-flash
MODEL_API_KEY=your-api-key
DATABASE_URL=postgresql://user:password@host:5432/dbname
REDIS_URL=redis://:password@host:6379/0
DEBUG=False
```

3. Run with Docker Compose:
```bash
docker-compose up
```

Or run directly:
```bash
uvicorn main:app --reload
```

## API Documentation

Once running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Architecture

- **FastAPI**: Web framework
- **Pydantic AI**: AI agent framework
- **PostgreSQL/Supabase**: Database
- **Redis**: Caching and session management

## Agents

All agents are in `backend/chatbot/agents/` and inherit from `BaseAgent`.

## Database

Database models are in `backend/db/models.py`. Run migrations or create tables automatically on startup.

## Testing

```bash
pytest backend/tests/
```
