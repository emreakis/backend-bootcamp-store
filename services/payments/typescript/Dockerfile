# Build context is the REPO ROOT, so this image can reach both the service and the
# contract it is generated from:
#     docker build -f services/payments/typescript/Dockerfile .
FROM node:22-alpine AS build

# protobuf gives us protoc; protobuf-dev gives us the well-known types, which is where
# google/protobuf/timestamp.proto comes from.
RUN apk add --no-cache protobuf protobuf-dev

WORKDIR /src
COPY services/payments/typescript/package.json ./
RUN npm install --no-audit --no-fund

# NOTHING EXISTS UNTIL THE CONTRACT DOES.
#
# ts-proto is a protoc plugin like any other — protoc parses the .proto and hands the
# result to it, exactly as it hands the result to protoc-gen-go. Same tool, same file,
# different back end.
#
# This produces the ServiceDefinition `server.addService` registers, so deleting a method
# from the .proto stops this build rather than producing a server that silently answers
# UNIMPLEMENTED for something it used to serve.
COPY contracts/proto /contracts
RUN mkdir -p src/gen && protoc -I /contracts -I /usr/include \
      --plugin=./node_modules/.bin/protoc-gen-ts_proto \
      --ts_proto_out=./src/gen \
      --ts_proto_opt=outputServices=grpc-js,esModuleInterop=true \
      bootcamp/payments/v1/payments.proto

COPY services/payments/typescript/tsconfig.json ./
COPY services/payments/typescript/src ./src
RUN npm run build

FROM node:22-alpine
WORKDIR /app

# Only what is needed to RUN. The compiler, the protobuf toolchain and every devDep stay
# in the build stage — a smaller image is a smaller attack surface, and shipping a code
# generator to production is shipping a way to change the code in production.
#
# @bufbuild/protobuf is a runtime dependency, not a dev one: ts-proto only runs at build
# time, but the code it emits imports @bufbuild/protobuf/wire for encoding on every call.
# Generated code drags its runtime along.
COPY services/payments/typescript/package.json ./
RUN npm install --omit=dev --no-audit --no-fund && npm cache clean --force
COPY --from=build /src/dist ./dist

# Configuration lives in the environment, never in the image.
ENV NODE_ENV=production \
    PORT=50051 \
    PAYMENT_DECLINE_OVER_CENTS=500000 \
    PAYMENT_ALWAYS_DECLINE=false \
    PAYMENT_LATENCY_MS=0

EXPOSE 50051
CMD ["node", "dist/server.js"]
