# Build context is the REPO ROOT, for consistency with every other service image:
#     docker build -f services/catalog/csharp/Dockerfile .
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build

WORKDIR /src
COPY services/catalog/csharp/Catalog.csproj ./
RUN dotnet restore

COPY services/catalog/csharp/*.cs ./
RUN dotnet publish -c Release -o /out

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /out ./

# The healthcheck in compose reaches for wget or curl; the aspnet image has neither, so
# install one. Worth noticing rather than hiding: a container that cannot be probed is a
# container the platform cannot tell is broken.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Configuration lives in the environment, never in the image.
ENV PORT=8000 \
    DATABASE_URL=postgres://store:store@catalog-db:5432/catalog

EXPOSE 8000
ENTRYPOINT ["dotnet", "Catalog.dll"]
