# Build context is the REPO ROOT, so this image can reach both the service and the
# contract it is generated from:
#     docker build -f services/payments/python/Dockerfile .
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir \
      "grpcio>=1.71" "grpcio-tools>=1.71" \
      "grpcio-health-checking>=1.71" "grpcio-reflection>=1.71"

# NOTHING EXISTS UNTIL THE CONTRACT DOES.
#
# This step runs before any of our source is even copied in, and it produces the
# servicer base class server.py inherits from. Delete a method from the .proto and this
# service stops implementing it — which is the difference between a contract and a
# description.
#
# The generated package lands at ./bootcamp/payments/v1/ because that is the path the
# .proto was found at relative to -I. protoc derives module names from paths, so the
# directory layout in contracts/proto IS the namespace.
COPY contracts/proto /contracts/proto
RUN python -m grpc_tools.protoc -I /contracts/proto \
      --python_out=. --pyi_out=. --grpc_python_out=. \
      bootcamp/payments/v1/payments.proto

COPY services/payments/python/server.py ./

# Configuration lives in the environment, never in the image.
ENV PORT=50051 \
    PAYMENT_DECLINE_OVER_CENTS=500000 \
    PAYMENT_ALWAYS_DECLINE=false \
    PAYMENT_LATENCY_MS=0

EXPOSE 50051
CMD ["python", "server.py"]
