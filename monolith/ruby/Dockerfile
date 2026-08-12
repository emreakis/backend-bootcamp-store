# Build context is the REPO ROOT:
#     docker build -f monolith/ruby/Dockerfile .
FROM ruby:3.4-slim

WORKDIR /app

# Gemfile first, so a source-only change reuses the cached bundle layer.
COPY monolith/ruby/Gemfile ./

# The sqlite3 gem ships precompiled native gems, but puma depends on nio4r, which does
# not — so a C toolchain is genuinely required to install this bundle. It is added and
# removed inside a single layer, so the compiler never reaches the final image while
# the .so files it produced stay behind.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && bundle install --jobs 4 --retry 3 \
 && apt-get purge -y --auto-remove build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY monolith/ruby/ ./
COPY db /db

# Configuration lives in the environment, never in the image. The same image runs on a
# laptop and in production; only these values change.
ENV PORT=8080 \
    DATABASE_PATH=/tmp/store.db \
    SCHEMA_PATH=/db/schema.sql \
    SEED_PATH=/db/seed.sql \
    RESET_DB=true

EXPOSE 8080
CMD ["bundle", "exec", "ruby", "app.rb"]
