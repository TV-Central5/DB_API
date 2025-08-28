#!/usr/bin/env bash
set -e

# Nếu có cert từ secret -> ghi ra file
if [ -n "$CC_CA_CRT" ]; then
  printf "%s" "$CC_CA_CRT" > /app/cc-ca.crt
  export SSL_ROOT_CERT=/app/cc-ca.crt
fi

# Port mặc định 8080 (Fly.io mapping vào đây)
export PORT="${PORT:-8080}"

# Chạy gunicorn
exec gunicorn app:app -b 0.0.0.0:$PORT --workers=2 --threads=4 --timeout=120
