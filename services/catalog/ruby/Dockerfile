# Build context is the REPO ROOT, for consistency with every other service image:
#     docker build -f services/catalog/ruby/Dockerfile .
FROM ruby:3.4-slim

WORKDIR /app

# Gemfile first, so a source-only change reuses the cached bundle layer.
COPY services/catalog/ruby/Gemfile ./

# puma's nio4r and the pg gem both need a C toolchain. It is added and removed inside a
# single layer, so the compiler never reaches the final image while the .so files it
# produced stay behind.
#
# libpq5 (the runtime library, as opposed to libpq-dev the headers) has to survive the
# purge, hence the second install: --auto-remove would otherwise take with it the exact
# shared object the pg gem needs to open a connection.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && bundle install --jobs 4 --retry 3 \
 && apt-get purge -y --auto-remove build-essential libpq-dev \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

COPY services/catalog/ruby/ ./

# Configuration lives in the environment, never in the image.
ENV PORT=8000 \
    DATABASE_URL=postgres://store:store@catalog-db:5432/catalog

EXPOSE 8000
CMD ["bundle", "exec", "ruby", "app.rb"]
