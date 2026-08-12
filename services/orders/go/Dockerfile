# Build context is the REPO ROOT, so this image can reach both the service and the
# contract its gRPC client is generated from:
#     docker build -f services/orders/go/Dockerfile .
FROM golang:1.25-alpine AS build

# protobuf gives us protoc; protobuf-dev gives us the well-known types, which is where
# google/protobuf/timestamp.proto comes from.
RUN apk add --no-cache protobuf protobuf-dev

# The two code generators, pinned. Pinned rather than @latest because a code generator
# is a build input: floating it means the bytes this image ships can change without a
# single line of our source changing. protoc-gen-go-grpc v1.6 is also what requires the
# Go 1.25 base above.
RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.12 \
 && go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.6.2

WORKDIR /src
COPY services/orders/go/go.mod ./
COPY contracts/proto /contracts

# NOTHING EXISTS UNTIL THE CONTRACT DOES.
#
# This runs before any of our source is copied in, and it produces the client stub that
# payments_client.go calls. Delete a method from the .proto and this build fails —
# which is the difference between a contract and a description.
#
# It is the same command the payments service runs, against the same file, with the
# same module path. Both sides of the contract import the identical generated package
# because both were produced from the identical bytes.
RUN protoc -I /contracts -I /usr/include \
      --go_out=. --go_opt=module=github.com/backendguru/store \
      --go-grpc_out=. --go-grpc_opt=module=github.com/backendguru/store \
      bootcamp/payments/v1/payments.proto

COPY services/orders/go/*.go ./
RUN go mod tidy && CGO_ENABLED=0 go build -trimpath -o /out/orders .

FROM alpine:3.21
COPY --from=build /out/orders /orders

# Configuration lives in the environment, never in the image. Note that no address
# appears here: CATALOG_URL and PAYMENTS_ADDR are supplied by the platform, because the
# same image has to run against compose today and a cluster tomorrow.
ENV PORT=8080 \
    CATALOG_TIMEOUT_MS=1000 \
    PAYMENTS_TIMEOUT_MS=2000 \
    PAYMENTS_RETRY_MAX=2 \
    BREAKER_FAILURE_THRESHOLD=5 \
    BREAKER_RESET_MS=10000

EXPOSE 8080
CMD ["/orders"]
