# Build context is the REPO ROOT, so this image can reach both the service and the
# contract it is generated from:
#     docker build -f services/payments/java/Dockerfile .
FROM maven:3.9-eclipse-temurin-21 AS build

WORKDIR /src
COPY services/payments/java/pom.xml ./

# The contract, copied to the path the pom's -Dproto.dir points at below.
#
# NOTHING EXISTS UNTIL THE CONTRACT DOES: this produces the service base class
# PaymentsServer extends. Delete a method from the .proto and this build stops
# compiling.
#
# protoc and the grpc-java plugin are downloaded from Maven Central as prebuilt binaries
# for the detected OS and CPU — which is why nothing has to be apt-installed here,
# unlike the Go and Node images.
COPY contracts/proto /contracts/proto

COPY services/payments/java/src ./src
RUN mvn -B -q -Dproto.dir=/contracts/proto package

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /src/target/payments.jar ./payments.jar

# Configuration lives in the environment, never in the image.
ENV PORT=50051 \
    PAYMENT_DECLINE_OVER_CENTS=500000 \
    PAYMENT_ALWAYS_DECLINE=false \
    PAYMENT_LATENCY_MS=0

EXPOSE 50051
CMD ["java", "-jar", "payments.jar"]
