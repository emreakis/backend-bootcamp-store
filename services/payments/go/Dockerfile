# Build context is the REPO ROOT, so this image can reach both the service and the
# contract it is generated from:
#     docker build -f services/payments/go/Dockerfile .
FROM golang:1.25-alpine AS build

# protobuf gives us protoc; protobuf-dev gives us the well-known types, which is where
# google/protobuf/timestamp.proto comes from.
RUN apk add --no-cache protobuf protobuf-dev

# The two code generators, pinned. protoc itself knows nothing about Go or gRPC — it
# parses the .proto and hands the result to plugins, which is why every language gets
# its own pair and why the toolchain is the same shape everywhere.
#
# Pinned rather than @latest because a code generator is a build input: floating it
# means the bytes this image ships can change without a single line of our source
# changing. protoc-gen-go-grpc v1.6 is also what requires the Go 1.25 base above.
RUN go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.12 \
 && go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@v1.6.2

WORKDIR /src
COPY services/payments/go/go.mod ./
COPY contracts/proto /contracts

# NOTHING EXISTS UNTIL THE CONTRACT DOES.
#
# This step runs before any of our source is even copied in, and it produces the
# server interface that main.go implements. Delete a method from the .proto and this
# build fails — which is the difference between a contract and a description.
#
# `module=` strips the module prefix from the go_package option, so the files land in
# ./gen/paymentsv1 exactly where the import in main.go expects them.
RUN protoc -I /contracts -I /usr/include \
      --go_out=. --go_opt=module=github.com/backendguru/store \
      --go-grpc_out=. --go-grpc_opt=module=github.com/backendguru/store \
      bootcamp/payments/v1/payments.proto

COPY services/payments/go/*.go ./
RUN go mod tidy && CGO_ENABLED=0 go build -trimpath -o /out/payments .

FROM alpine:3.21
COPY --from=build /out/payments /payments

# Configuration lives in the environment, never in the image.
ENV PORT=50051 \
    PAYMENT_DECLINE_OVER_CENTS=500000 \
    PAYMENT_ALWAYS_DECLINE=false \
    PAYMENT_LATENCY_MS=0

EXPOSE 50051
CMD ["/payments"]
