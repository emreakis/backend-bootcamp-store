# Build context is the REPO ROOT, so this image can reach both the service and the
# contract its gRPC client is generated from:
#     docker build -f services/orders/ruby/Dockerfile .
FROM ruby:3.4-slim

WORKDIR /app

# Gemfile first, so a source-only change reuses the cached bundle layer.
COPY services/orders/ruby/Gemfile ./

# grpc and pg both need a C toolchain — grpc has no precompiled gem for this platform,
# and pg links against libpq. Both are added and removed inside a single layer, so the
# compiler never reaches the final image while the .so files it produced stay behind.
#
# libpq5 (the runtime library, as opposed to libpq-dev the headers) has to survive the
# purge, hence the second install: --auto-remove would otherwise take with it the exact
# shared object the pg gem needs to open a connection. That is the sort of thing you
# discover at runtime, in a container, at the least convenient moment.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && bundle install --jobs 4 --retry 3 \
 && apt-get purge -y --auto-remove build-essential libpq-dev \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

# NOTHING EXISTS UNTIL THE CONTRACT DOES.
#
# grpc-tools ships its own protoc and its own Ruby plugin, so this is the same tool the
# Go and TypeScript images run, invoked through a wrapper script. It runs before our
# source is copied, and it produces the stub payments_client.rb requires — delete a
# method from the .proto and this app stops loading.
#
# Two files come out: _pb.rb for the messages and _services_pb.rb for the service. That
# split is a protobuf idea, not a Ruby one — messages are useful without a service, and
# plenty of projects generate only the first half.
COPY contracts/proto /contracts/proto
RUN mkdir -p gen && bundle exec grpc_tools_ruby_protoc \
      -I /contracts/proto \
      --ruby_out=gen --grpc_out=gen \
      bootcamp/payments/v1/payments.proto

COPY services/orders/ruby/ ./

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
CMD ["bundle", "exec", "ruby", "app.rb"]
