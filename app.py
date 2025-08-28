# FILE: app.py
import os
import io
import csv
from flask import Flask, request, jsonify, Response, abort
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Tải biến môi trường khi chạy LOCAL (trên Render bạn cấu hình ENV trong console)
load_dotenv()

app = Flask(__name__)

# ====== Auth đơn giản bằng API key trong header ======
API_KEY = os.getenv("API_KEY", "mykey123")

def require_key():
    key = request.headers.get("X-API-Key")
    if not API_KEY or key != API_KEY:
        abort(401, description="Unauthorized")

# ====== Kết nối CockroachDB qua wire PostgreSQL (psycopg3) ======
def get_conn():
    """
    Tạo connection tới CockroachDB.
    Dùng sslmode=verify-full + sslrootcert (CA) theo yêu cầu Cockroach Cloud.
    Nếu cluster cần routing, thêm options=--cluster=<CLUSTER_FLAG>.
    """
    dsn = (
        f"host={os.getenv('DB_HOST')} "
        f"port={os.getenv('DB_PORT', '26257')} "
        f"dbname={os.getenv('DB_NAME')} "
        f"user={os.getenv('DB_USER')} "
        f"password={os.getenv('DB_PASSWORD')} "
        f"sslmode={os.getenv('SSL_MODE', 'verify-full')} "
        f"sslrootcert={os.getenv('SSL_ROOT_CERT')}"
    )
    cluster = os.getenv("CLUSTER_FLAG")
    if cluster:
        dsn += f" options=--cluster={cluster}"
    return psycopg.connect(dsn)

@app.get("/health")
def health():
    return {"status": "ok"}

# ====== WHITELIST câu SQL được phép gọi từ Excel ======
ALLOWED_QUERIES = {
    # Kiểm tra kết nối
    "now": "SELECT now() AS server_time",

    # Liệt kê bảng (bỏ qua system schemas)
    "tables": """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('pg_catalog','information_schema')
        ORDER BY table_schema, table_name
        LIMIT %(limit)s OFFSET %(offset)s
    """,

    # Ví dụ đọc bảng public.detail (đổi theo bảng thật của bạn)
    "detail_all": """
        SELECT *
        FROM public.detail
        ORDER BY 1
        LIMIT %(limit)s OFFSET %(offset)s
    """,

    # Nếu bảng có cột updated_at (kiểu timestamptz), lọc theo khoảng thời gian
    "detail_range": """
        SELECT *
        FROM public.detail
        WHERE (%(from)s IS NULL OR updated_at >= %(from)s::timestamptz)
          AND (%(to)s   IS NULL OR updated_at <  %(to)s::timestamptz)
        ORDER BY updated_at DESC NULLS LAST
        LIMIT %(limit)s OFFSET %(offset)s
    """,
}

def normalize_pagination(args, default_limit=100):
    """Giới hạn limit/offset để tránh query quá lớn."""
    try:
        limit = int(args.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0

    if limit > 5000:
        limit = 5000
    if offset < 0:
        offset = 0
    return limit, offset

# ====== Endpoint JSON: /query?q=<key>&limit=&offset=&from=&to= ======
@app.get("/query")
def query_json():
    require_key()
    q = request.args.get("q", "now")
    if q not in ALLOWED_QUERIES:
        abort(400, description=f"Query not allowed. Use one of: {', '.join(ALLOWED_QUERIES.keys())}")

    limit, offset = normalize_pagination(request.args)
    from_dt = request.args.get("from")  # ví dụ: 2025-01-01
    to_dt   = request.args.get("to")    # ví dụ: 2025-02-01
    sql = ALLOWED_QUERIES[q]

    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"limit": limit, "offset": offset, "from": from_dt, "to": to_dt})
        rows = cur.fetchall()
    return jsonify(rows)

# ====== Endpoint CSV: /query.csv?q=<key>&... ======
@app.get("/query.csv")
def query_csv():
    require_key()
    q = request.args.get("q", "now")
    if q not in ALLOWED_QUERIES:
        abort(400, description=f"Query not allowed. Use one of: {', '.join(ALLOWED_QUERIES.keys())}")

    limit, offset = normalize_pagination(request.args, default_limit=1000)
    from_dt = request.args.get("from")
    to_dt   = request.args.get("to")
    sql = ALLOWED_QUERIES[q]

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, {"limit": limit, "offset": offset, "from": from_dt, "to": to_dt})
        cols = [d.name for d in cur.description]  # psycopg3: dùng d.name
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)
        writer.writerows(cur.fetchall())

    return Response(buf.getvalue(), mimetype="text/csv")

# ====== Xử lý lỗi gọn ======
@app.errorhandler(400)
def bad_request(e):
    return jsonify(error=str(e)), 400

@app.errorhandler(401)
def unauthorized(e):
    return jsonify(error=str(e)), 401

@app.errorhandler(500)
def server_error(e):
    return jsonify(error="Internal Server Error"), 500
# ====== DEBUG (tạm thời, giúp chẩn đoán) ======
import socket
from psycopg.rows import dict_row

@app.get("/debug/env")
def debug_env():
    return {
        "DB_HOST": os.getenv("DB_HOST"),
        "DB_PORT": os.getenv("DB_PORT"),
        "DB_NAME": os.getenv("DB_NAME"),
        "DB_USER": os.getenv("DB_USER"),
        "SSL_MODE": os.getenv("SSL_MODE"),
        "SSL_ROOT_CERT": os.getenv("SSL_ROOT_CERT"),
        "CLUSTER_FLAG": os.getenv("CLUSTER_FLAG"),
    }

@app.get("/dbping")
def dbping():
    try:
        host = os.getenv("DB_HOST")
        # 1) thử resolve DNS
        socket.getaddrinfo(host, None)

        # 2) thử truy vấn đơn giản
        with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT version() AS version, now() AS now")
            row = cur.fetchone()
        return {"ok": True, "version": row["version"], "now": row["now"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500
