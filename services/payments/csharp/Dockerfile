# Build context is the REPO ROOT, so this image can reach both the service and the
# contract it is generated from:
#     docker build -f services/payments/csharp/Dockerfile .
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build

WORKDIR /src
COPY services/payments/csharp/Payments.csproj ./

# The contract, at the path -p:ProtoDir points at below.
#
# NOTHING EXISTS UNTIL THE CONTRACT DOES: Grpc.Tools runs protoc during compilation and
# feeds the generated C# straight to the compiler, so nothing lands in git and nothing
# can drift. Delete a method from the .proto and this build stops working.
COPY contracts/proto /contracts/proto

RUN dotnet restore -p:ProtoDir=/contracts/proto

COPY services/payments/csharp/*.cs ./
RUN dotnet publish -c Release -o /out -p:ProtoDir=/contracts/proto

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /out ./

# Configuration lives in the environment, never in the image.
ENV PORT=50051 \
    PAYMENT_DECLINE_OVER_CENTS=500000 \
    PAYMENT_ALWAYS_DECLINE=false \
    PAYMENT_LATENCY_MS=0

EXPOSE 50051
ENTRYPOINT ["dotnet", "Payments.dll"]
