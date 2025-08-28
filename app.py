# FILE: app.py
import os, io, csv
from flask import Flask, request, jsonify, Response, abort
from psycopg2.extras import RealDictCursor
import psycopg2
from dotenv import load_dotenv

# Load .env khi chạy local (trên Render sẽ dùng ENV do bạn nhập)
load_dotenv()

app = Flask(__name__)

API_KEY = os.getenv("API_KEY", "mykey123")

def require_key():
    key = request.headers.get("X-API-Key")
    if not API_KEY or key != API_KEY:
        abort(401, description="Unauthorized")

def get_conn():
    # DSN kết nối CockroachDB (Postgres wire)
    dsn = (
        f"host={os.getenv('DB_HOST')} "
        f"port={os.getenv('DB_PORT','26257')} "
        f"dbname={os.getenv('DB_NAME')} "
        f"user={os.getenv('DB_USER')} "
        f"password={os.getenv('DB_PASSWORD')} "
        f"sslmode={os.getenv('SSL_MODE','verify-full')} "
        f"sslrootcert={os.getenv('SSL_ROOT_CERT')}"
    )
    cluster = os.getenv("CLUSTER_FLAG")
    if cluster:
        dsn += f" options=--cluster={cluster}"
    return psycopg2.connect(dsn)

@app.get("/health")
def health():
    return {"status": "ok"}

# WHITELIST câu truy vấn an toàn (bạn có thể chỉnh tuỳ bảng)
ALLOWED_QUERIES = {
    # Kiểm tra kết nối DB
    "now": "SELECT now() AS server_time",

    # Liệt kê bảng user-space (bỏ qua pg_catalog/information_schema)
    "tables": """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type='BASE TABLE'
          AND table_schema NOT IN ('pg_catalog','information_schema')
        ORDER BY table_schema, table_name
        LIMIT %(limit)s OFFSET %(offset)s
    """,

    # Ví dụ đọc bảng public.detail (nếu bạn có bảng này)
    "detail_all": """
        SELECT * FROM public.detail
        ORDER BY 1
        LIMIT %(limit)s OFFSET %(offset)s
    """,

    # Nếu bảng có cột updated_at dạng timestamptz thì dùng cái này
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
    limit = int(args.get("limit", default_limit))
    offset = int(args.get("offset", 0))
    if limit > 5000: limit = 5000
    if offset < 0: offset = 0
    return limit, offset

@app.get("/query")
def query_json():
    require_key()
    q = request.args.get("q", "now")
    if q not in ALLOWED_QUERIES:
        abort(400, description=f"Query not allowed. Use one of: {', '.join(ALLOWED_QUERIES.keys())}")

    limit, offset = normalize_pagination(request.args)
    from_dt = request.args.get("from")
    to_dt   = request.args.get("to")
    sql = ALLOWED_QUERIES[q]

    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, {"limit": limit, "offset": offset, "from": from_dt, "to": to_dt})
        rows = cur.fetchall()
    return jsonify(rows)

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
        cols = [d[0] for d in cur.description]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)
        writer.writerows(cur.fetchall())
    return Response(buf.getvalue(), mimetype="text/csv")

@app.errorhandler(400)
def bad_request(e): return jsonify(error=str(e)), 400

@app.errorhandler(401)
def unauthorized(e): return jsonify(error=str(e)), 401

@app.errorhandler(500)
def server_error(e): return jsonify(error="Internal Server Error"), 500
