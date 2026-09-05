FROM eclipse-temurin:21-jre
WORKDIR /theta
COPY ThetaTerminalv3.jar /theta/ThetaTerminalv3.jar
COPY config.toml /theta/config.toml
COPY entrypoint.sh /theta/entrypoint.sh
RUN chmod +x /theta/entrypoint.sh
EXPOSE 25503
ENTRYPOINT ["/theta/entrypoint.sh"]
