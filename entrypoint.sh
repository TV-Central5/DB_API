# FILE: entrypoint.sh
#!/usr/bin/env bash
set -e

# Nếu bạn truyền CA cert qua secret CC_CA_CRT thì ghi ra file
if [ -n "$CC_CA_CRT" ]; then
  echo "Writing Cockroach CA cert to /app/cc-ca.crt"
  printf "%s" "$CC_CA_CRT" > /app/cc-ca.crt
  export SSL_ROOT_CERT=/app/cc-ca.crt
fi

# Port chuẩn cho Fly (đừng đổi)
export PORT="${PORT:-8080}"

# Chạy gunicorn
exec gunicorn app:app -b 0.0.0.0:$PORT --workers=2 --threads=4 --timeout=120
