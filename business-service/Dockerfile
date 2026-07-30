FROM maven:3.9.16-eclipse-temurin-21 AS build

WORKDIR /source
COPY pom.xml .
COPY src ./src
RUN mvn --batch-mode -DskipTests package

FROM eclipse-temurin:21-jre

WORKDIR /service
COPY --from=build /source/target/business-service-0.1.0-SNAPSHOT.jar /service/app.jar

EXPOSE 8080
CMD ["java", "-jar", "/service/app.jar"]
