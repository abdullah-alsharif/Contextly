FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY backend/app ./app
# Pre-deploy migrations (`python -m app.migrate`) read this from the image.
COPY infrastructure/migrations ./infrastructure/migrations

EXPOSE 8000

# Render free has no worker service type — run it alongside uvicorn in the web
# container; the wake cron keeps the service awake (docs/deployment.md §2, §9).
CMD ["sh", "-c", "python -m app.worker & exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]