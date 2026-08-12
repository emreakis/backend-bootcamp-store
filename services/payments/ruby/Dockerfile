# Build context is the REPO ROOT, so this image can reach both the service and the
# contract it is generated from:
#     docker build -f services/payments/ruby/Dockerfile .
FROM ruby:3.4-slim

WORKDIR /app

# Gemfile first, so a source-only change reuses the cached bundle layer.
COPY services/payments/ruby/Gemfile ./

# grpc has no precompiled gem for this platform, so a C toolchain is genuinely required
# to install this bundle. It is added and removed inside a single layer, so the compiler
# never reaches the final image while the .so files it produced stay behind.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && bundle install --jobs 4 --retry 3 \
 && apt-get purge -y --auto-remove build-essential \
 && rm -rf /var/lib/apt/lists/*

# NOTHING EXISTS UNTIL THE CONTRACT DOES.
#
# grpc-tools ships its own protoc and its own Ruby plugin, so this is the same tool the
# Go, TypeScript and C# images run, invoked through a wrapper script. It runs before our
# source is copied, and it produces the service class server.rb inherits from — delete a
# method from the .proto and this app stops implementing it.
COPY contracts/proto /contracts/proto
RUN mkdir -p gen && bundle exec grpc_tools_ruby_protoc \
      -I /contracts/proto \
      --ruby_out=gen --grpc_out=gen \
      bootcamp/payments/v1/payments.proto

COPY services/payments/ruby/ ./

# Configuration lives in the environment, never in the image.
ENV PORT=50051 \
    PAYMENT_DECLINE_OVER_CENTS=500000 \
    PAYMENT_ALWAYS_DECLINE=false \
    PAYMENT_LATENCY_MS=0

EXPOSE 50051
CMD ["bundle", "exec", "ruby", "server.rb"]
