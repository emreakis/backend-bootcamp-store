# Build context is the REPO ROOT, for consistency with every other service image:
#     docker build -f services/catalog/java/Dockerfile .
FROM maven:3.9-eclipse-temurin-21 AS build

WORKDIR /src
COPY services/catalog/java/pom.xml ./
COPY services/catalog/java/src ./src
RUN mvn -B -q package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /src/target/catalog.jar ./catalog.jar

# Configuration lives in the environment, never in the image.
ENV PORT=8000 \
    DATABASE_URL=postgres://store:store@catalog-db:5432/catalog

EXPOSE 8000
CMD ["java", "-jar", "catalog.jar"]
