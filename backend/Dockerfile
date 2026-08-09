FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# Dev compose overrides the command to add --reload; this is the prod default.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]