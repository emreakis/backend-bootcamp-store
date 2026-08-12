# Build context is the REPO ROOT, so this image can copy both the application and
# the shared db/ directory:
#     docker build -f monolith/python/Dockerfile .
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.32"

COPY monolith/python/app ./app
COPY db /db

# Configuration lives in the environment, never in the image. The same image runs
# on a laptop and in production; only these values change.
ENV PORT=8080 \
    DATABASE_PATH=/tmp/store.db \
    SCHEMA_PATH=/db/schema.sql \
    SEED_PATH=/db/seed.sql \
    RESET_DB=true

EXPOSE 8080
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
