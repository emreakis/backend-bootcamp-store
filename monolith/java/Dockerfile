# Build context is the REPO ROOT:
#     docker build -f monolith/java/Dockerfile .
FROM maven:3.9-eclipse-temurin-21 AS build

WORKDIR /src
# pom.xml first, so a source-only change reuses the cached dependency layer.
COPY monolith/java/pom.xml ./
RUN mvn -B -q dependency:go-offline
COPY monolith/java/src ./src
RUN mvn -B -q package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /src/target/store.jar ./store.jar
COPY db /db

# Configuration lives in the environment, never in the image. The same image runs on a
# laptop and in production; only these values change.
ENV PORT=8080 \
    DATABASE_PATH=/tmp/store.db \
    SCHEMA_PATH=/db/schema.sql \
    SEED_PATH=/db/seed.sql \
    RESET_DB=true

EXPOSE 8080
CMD ["java", "-jar", "store.jar"]
