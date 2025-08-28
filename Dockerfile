# FILE: Dockerfile
FROM python:3.11-slim

# Không ghi cache .pyc, flush stdout ngay
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# Cài thêm bash, certs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl bash && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements và cài
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy code app
COPY app.py .
COPY entrypoint.sh .

# Fix CRLF (từ Windows sang Linux) và chmod để script chạy được
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

EXPOSE 8080

CMD ["/app/entrypoint.sh"]
