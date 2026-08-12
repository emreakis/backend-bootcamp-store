# Build context is the REPO ROOT, so this image can reach both the service and the
# contract its gRPC client is generated from:
#     docker build -f services/orders/java/Dockerfile .
FROM maven:3.9-eclipse-temurin-21 AS build

WORKDIR /src
COPY services/orders/java/pom.xml ./

# The contract, copied to the path the pom's -Dproto.dir points at below. protoc and
# the grpc-java plugin are downloaded from Maven Central as prebuilt binaries for the
# detected OS and CPU — which is why nothing has to be installed for this to work.
COPY contracts/proto /contracts/proto

COPY services/orders/java/src ./src
RUN mvn -B -q -Dproto.dir=/contracts/proto package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /src/target/orders.jar ./orders.jar

# Configuration lives in the environment, never in the image. Note that no address
# appears here: CATALOG_URL and PAYMENTS_ADDR are supplied by the platform, because
# the same image has to run against compose today and a cluster tomorrow.
ENV PORT=8080 \
    CATALOG_TIMEOUT_MS=1000 \
    PAYMENTS_TIMEOUT_MS=2000 \
    PAYMENTS_RETRY_MAX=2 \
    BREAKER_FAILURE_THRESHOLD=5 \
    BREAKER_RESET_MS=10000

EXPOSE 8080
CMD ["java", "-jar", "orders.jar"]
