# FILE: Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Cài deps hệ thống nhẹ cho psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Cài Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Thêm app
COPY app.py .
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh

# Fly sẽ gọi cổng 8080
EXPOSE 8080

# Chạy bằng Gunicorn qua entrypoint (ghi CA cert nếu có)
CMD ["/app/entrypoint.sh"]
