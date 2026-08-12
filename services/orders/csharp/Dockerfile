# Build context is the REPO ROOT, so this image can reach both the service and the
# contract its gRPC client is generated from:
#     docker build -f services/orders/csharp/Dockerfile .
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build

WORKDIR /src
COPY services/orders/csharp/Orders.csproj ./

# The contract, at the path -p:ProtoDir points at below.
#
# NOTHING EXISTS UNTIL THE CONTRACT DOES: Grpc.Tools runs protoc during compilation and
# feeds the generated C# straight to the compiler, so nothing lands in git and nothing
# can drift. Delete a method from the .proto and this build stops working.
#
# protoc and the C# gRPC plugin arrive as prebuilt binaries inside the Grpc.Tools NuGet
# package for the detected OS and CPU — which is why nothing has to be apt-installed
# here, unlike the Go and TypeScript images.
COPY contracts/proto /contracts/proto

# Restore before copying source, so a code change does not re-download the world.
RUN dotnet restore -p:ProtoDir=/contracts/proto

COPY services/orders/csharp/*.cs ./
RUN dotnet publish -c Release -o /out -p:ProtoDir=/contracts/proto

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /out ./

# The healthcheck in compose reaches for wget or curl; the aspnet image has neither, so
# install one. Worth noticing rather than hiding: a container that cannot be probed is a
# container the platform cannot tell is broken.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

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
ENTRYPOINT ["dotnet", "Orders.dll"]
