# Build context is the REPO ROOT, so this image can copy both the application and the
# shared db/ directory:
#     docker build -f monolith/go/Dockerfile .
FROM golang:1.24-alpine AS build

WORKDIR /src
COPY monolith/go/go.mod monolith/go/go.sum ./
RUN go mod download
COPY monolith/go/ ./
# CGO off: modernc.org/sqlite is a pure-Go SQLite, so the binary is static and the
# runtime image needs no C library at all.
RUN CGO_ENABLED=0 go build -trimpath -o /out/store .

FROM alpine:3.21
WORKDIR /app
COPY --from=build /out/store /app/store
COPY db /db

# Configuration lives in the environment, never in the image. The same image runs on a
# laptop and in production; only these values change.
ENV PORT=8080 \
    DATABASE_PATH=/tmp/store.db \
    SCHEMA_PATH=/db/schema.sql \
    SEED_PATH=/db/seed.sql \
    RESET_DB=true

EXPOSE 8080
CMD ["/app/store"]
