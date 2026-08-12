# Build context is the REPO ROOT, for consistency with every other service image:
#     docker build -f services/catalog/go/Dockerfile .
#
# This one does not actually need the repo root — catalog has no contract to generate
# from, because it speaks HTTP and its contract is an OpenAPI document that describes
# code rather than producing it. That asymmetry with the gRPC services is the point of
# Session 2's second half.
FROM golang:1.25-alpine AS build

WORKDIR /src
COPY services/catalog/go/go.mod ./
COPY services/catalog/go/*.go ./
RUN go mod tidy && CGO_ENABLED=0 go build -trimpath -o /out/catalog .

FROM alpine:3.21
COPY --from=build /out/catalog /catalog

# Configuration lives in the environment, never in the image.
ENV PORT=8000 \
    DATABASE_URL=postgres://store:store@catalog-db:5432/catalog

EXPOSE 8000
CMD ["/catalog"]
