FROM node:22-slim
RUN useradd -m -u 1001 -s /usr/sbin/nologin cc \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g @anthropic-ai/claude-code@2.1.201
COPY entrypoint.sh /usr/local/bin/cc-entry
RUN chmod 755 /usr/local/bin/cc-entry
USER cc
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/cc-entry"]
