# Build context is the REPO ROOT, so this image can reach both the service and the
# contract its gRPC client is generated from:
#     docker build -f services/orders/typescript/Dockerfile .
FROM node:22-alpine AS build

# protobuf gives us protoc; protobuf-dev gives us the well-known types, which is where
# google/protobuf/timestamp.proto comes from.
RUN apk add --no-cache protobuf protobuf-dev

WORKDIR /src
COPY services/orders/typescript/package.json ./
RUN npm install --no-audit --no-fund

# NOTHING EXISTS UNTIL THE CONTRACT DOES.
#
# ts-proto is a protoc plugin like any other — protoc parses the .proto and hands the
# result to it, exactly as it hands the result to protoc-gen-go for the Go services.
# Same tool, same file, different back end.
#
# This runs before `tsc` ever sees our source, and it produces the typed client that
# payments.client.ts imports. Delete a field from the .proto and this stops
# type-checking, which is the difference between a contract and a description.
#
# The Node ecosystem's usual habit is @grpc/proto-loader, which reads the .proto at
# RUNTIME and hands you `any`. That works, and it moves every contract mismatch from
# build time to 3am. Generating is the same choice Java, Go and C# make here.
COPY contracts/proto /contracts
RUN mkdir -p src/gen && protoc -I /contracts -I /usr/include \
      --plugin=./node_modules/.bin/protoc-gen-ts_proto \
      --ts_proto_out=./src/gen \
      --ts_proto_opt=outputServices=grpc-js,esModuleInterop=true \
      bootcamp/payments/v1/payments.proto

COPY services/orders/typescript/tsconfig.json ./
COPY services/orders/typescript/src ./src
RUN npm run build

# ---------------------------------------------------------------------------
FROM node:22-alpine
WORKDIR /app

# Only what is needed to RUN. The compiler, the protobuf toolchain and every devDep
# stay in the build stage — a smaller image is a smaller attack surface, and shipping
# a code generator to production is shipping a way to change the code in production.
#
# `@bufbuild/protobuf` is a runtime dependency, not a dev one, and the distinction bit
# once already: ts-proto is a devDependency because it only runs at build time, but the
# code it emits imports @bufbuild/protobuf/wire for encoding on every call. Generated
# code drags its runtime along — the same lesson the Java service learned the harder
# way, where a protoc/protobuf-java version mismatch failed at compile time instead.
COPY services/orders/typescript/package.json ./
RUN npm install --omit=dev --no-audit --no-fund && npm cache clean --force
COPY --from=build /src/dist ./dist

# Configuration lives in the environment, never in the image. Note that no address
# appears here: CATALOG_URL and PAYMENTS_ADDR are supplied by the platform, because the
# same image has to run against compose today and a cluster tomorrow.
ENV NODE_ENV=production \
    PORT=8080 \
    CATALOG_TIMEOUT_MS=1000 \
    PAYMENTS_TIMEOUT_MS=2000 \
    PAYMENTS_RETRY_MAX=2 \
    BREAKER_FAILURE_THRESHOLD=5 \
    BREAKER_RESET_MS=10000

EXPOSE 8080
CMD ["node", "dist/main.js"]
