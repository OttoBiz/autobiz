FROM python:3.11-alpine

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Make the startup script executable
RUN chmod +x start.sh

EXPOSE 8000

ENV PYTHONPATH=/app

# Use the startup script instead of direct uvicorn command
CMD ["./start.sh"]