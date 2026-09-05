#!/usr/bin/env bash
# Point Python/urllib/requests at certifi CA bundle (macOS python.org SSL fix).
export_ssl_certs() {
  local py="${1:-python3}"
  if [[ ! -x "${py}" ]]; then
    py="python3"
  fi
  if "${py}" -m certifi >/dev/null 2>&1; then
    export SSL_CERT_FILE="$("${py}" -m certifi)"
    export REQUESTS_CA_BUNDLE="${SSL_CERT_FILE}"
  fi
}
