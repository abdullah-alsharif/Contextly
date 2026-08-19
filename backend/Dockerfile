FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY backend/app ./app
# Pre-deploy migrations (`python -m app.migrate`) read this from the image.
COPY infrastructure/migrations ./infrastructure/migrations

EXPOSE 8000

# One image for web + worker: the worker runs when CONTEXTLY_WORKER=1, else
# uvicorn binds $PORT (Render free allows no startCommand with a docker runtime).
CMD ["sh", "-c", "if [ \"$CONTEXTLY_WORKER\" = \"1\" ]; then python -m app.worker; else uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}; fi"]