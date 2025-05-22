#!/bin/sh

# Wait for database to be ready (optional but recommended)
echo "Waiting for database to be ready..."
sleep 5

# Initialize database
echo "Initializing database..."
python -c "from backend.db.init_db import init_db; init_db()"

# Start the application
echo "Starting application..."
exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload 