FROM eclipse-temurin:21-jdk AS build

WORKDIR /source
COPY src/Main.java .
RUN javac --release 21 -d /classes Main.java

FROM eclipse-temurin:21-jre

WORKDIR /service
COPY --from=build /classes /service/classes

EXPOSE 8080
CMD ["java", "--add-modules", "jdk.httpserver", "-cp", "/service/classes", "Main"]

