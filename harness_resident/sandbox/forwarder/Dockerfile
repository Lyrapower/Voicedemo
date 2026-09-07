FROM alpine:3.21
RUN apk add --no-cache socat python3
COPY proxy.py /usr/local/bin/egress_proxy.py
COPY start.sh /usr/local/bin/fwd-start
RUN chmod 755 /usr/local/bin/fwd-start /usr/local/bin/egress_proxy.py
ENTRYPOINT ["/usr/local/bin/fwd-start"]
