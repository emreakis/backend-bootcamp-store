# Build context is the REPO ROOT:
#     docker build -f monolith/typescript/Dockerfile .
FROM node:24-alpine AS build

WORKDIR /app
COPY monolith/typescript/package.json monolith/typescript/package-lock.json ./
RUN npm ci
COPY monolith/typescript/tsconfig.json ./
COPY monolith/typescript/src ./src
RUN npm run build

FROM node:24-alpine
WORKDIR /app
COPY monolith/typescript/package.json monolith/typescript/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist
COPY db /db

# Configuration lives in the environment, never in the image. The same image runs on a
# laptop and in production; only these values change.
ENV PORT=8080 \
    DATABASE_PATH=/tmp/store.db \
    SCHEMA_PATH=/db/schema.sql \
    SEED_PATH=/db/seed.sql \
    RESET_DB=true

EXPOSE 8080
CMD ["node", "dist/main.js"]
