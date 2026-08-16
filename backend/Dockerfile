FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY backend/app ./app
# Pre-deploy migrations (`python -m app.migrate`) read this from the image.
COPY infrastructure/migrations ./infrastructure/migrations

EXPOSE 8000

# Dev compose overrides the command to add --reload. Prod default: bind
# $PORT (Render web services require it; default 10000), fall back to 8000
# for bare `docker run`. Shell form so ${PORT} expands at container start.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]