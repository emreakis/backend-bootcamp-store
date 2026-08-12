# Build context is the REPO ROOT, for consistency with every other service image:
#     docker build -f services/catalog/typescript/Dockerfile .
FROM node:22-alpine AS build

WORKDIR /src
COPY services/catalog/typescript/package.json ./
RUN npm install --no-audit --no-fund

COPY services/catalog/typescript/tsconfig.json ./
COPY services/catalog/typescript/src ./src
RUN npm run build

FROM node:22-alpine
WORKDIR /app

# Only what is needed to RUN. The compiler and every devDep stay in the build stage —
# a smaller image is a smaller attack surface.
COPY services/catalog/typescript/package.json ./
RUN npm install --omit=dev --no-audit --no-fund && npm cache clean --force
COPY --from=build /src/dist ./dist

# Configuration lives in the environment, never in the image.
ENV NODE_ENV=production \
    PORT=8000 \
    DATABASE_URL=postgres://store:store@catalog-db:5432/catalog

EXPOSE 8000
CMD ["node", "dist/main.js"]
