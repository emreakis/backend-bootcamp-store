# Build context is the REPO ROOT, so this image can reach both the service and the
# contract its gRPC client is generated from:
#     docker build -f services/orders/python/Dockerfile .
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
      "fastapi>=0.115" "uvicorn[standard]>=0.32" "psycopg[binary,pool]>=3.2" \
      "httpx>=0.28" "grpcio>=1.71" "grpcio-tools>=1.71"

# The contract, and the code generated from it — BEFORE our source is copied.
#
# That ordering is the point. `payments_client.py` imports a module that does not
# exist in this repository, and if you delete a field from the .proto this build
# starts failing. A contract you can break the build with is a different kind of
# object from a contract you can only read.
#
# The generated package lands at ./bootcamp/payments/v1/ because that is the path the
# .proto was found at relative to -I. Hence the deep directory tree in contracts/proto
# — protoc derives module names from paths, so the layout IS the namespace.
COPY contracts/proto /contracts/proto
RUN python -m grpc_tools.protoc -I /contracts/proto \
      --python_out=. --pyi_out=. --grpc_python_out=. \
      bootcamp/payments/v1/payments.proto

COPY services/orders/python/app ./app

# Configuration lives in the environment, never in the image. Note that no address
# appears here: CATALOG_URL and PAYMENTS_ADDR are supplied by the platform, because
# the same image has to run against compose today and a cluster tomorrow.
ENV PORT=8080 \
    CATALOG_TIMEOUT_MS=1000 \
    PAYMENTS_TIMEOUT_MS=2000 \
    PAYMENTS_RETRY_MAX=2 \
    BREAKER_FAILURE_THRESHOLD=5 \
    BREAKER_RESET_MS=10000

EXPOSE 8080
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
