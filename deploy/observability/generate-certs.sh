#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$DIR/nginx/certs"
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout "$DIR/nginx/certs/server.key" \
  -out "$DIR/nginx/certs/server.crt" \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
chmod 600 "$DIR/nginx/certs/server.key"
echo "Generated $DIR/nginx/certs/server.crt and server.key (local demo only)."
