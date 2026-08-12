# Build context is the REPO ROOT:
#     docker build -f services/catalog/python/Dockerfile .
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
      "fastapi>=0.115" "uvicorn[standard]>=0.32" "psycopg[binary,pool]>=3.2"

COPY services/catalog/python/app ./app

ENV PORT=8000 \
    DATABASE_URL=postgres://store:store@catalog-db:5432/catalog

EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
