# Build context is the REPO ROOT:
#     docker build -f monolith/csharp/Dockerfile .
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build

WORKDIR /src
# csproj first, so a source-only change reuses the cached restore layer.
COPY monolith/csharp/Store.csproj ./
RUN dotnet restore
COPY monolith/csharp/ ./
RUN dotnet publish -c Release -o /out --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /out ./
COPY db /db

# Configuration lives in the environment, never in the image. The same image runs on a
# laptop and in production; only these values change.
ENV PORT=8080 \
    DATABASE_PATH=/tmp/store.db \
    SCHEMA_PATH=/db/schema.sql \
    SEED_PATH=/db/seed.sql \
    RESET_DB=true

EXPOSE 8080
CMD ["dotnet", "Store.dll"]
