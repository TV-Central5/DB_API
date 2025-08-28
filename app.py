# FILE: app.py
import os
import io
import csv
import re
import socket
from flask import Flask, request, jsonify, Response, abort
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Load .env (local); trên Fly.io sẽ dùng Environment Variables
load_dotenv()

app = Flask(__name__)

# ====== Auth bằng API Key ======
API_KEY = os.getenv("API_KEY", "central5")

def require_key():
    # Đổi header từ "X-API-Key" -> "API-KEY"
    key = request.headers.get("API-KEY")
    if not API_KEY or key != API_KEY:
        abort(401, description="Unauthorized")

# ====== Kết nối Cockroach/Postgres ======
def get_conn():
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

# ====== Trang chào ======
@app.get("/")
def index():
    return {
        "service": "DB API",
        "endpoints": ["/health", "/query", "/query.csv", "/table/<tbl>.csv"],
        "auth": "Header API-KEY",
    }

# ====== Health (không đụng DB) ======
@app.get("/health")
def health():
    return {"status": "ok"}

# ====== Query whitelist (giữ lại) ======
ALLOWED_QUERIES = {
    "now": "SELECT now() AS server_time",
    "tables": """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('pg_catalog','information_schema')
        ORDER BY table_schema, table_name
        LIMIT %(limit)s OFFSET %(offset)s
    """,
}

# ====== Pagination helper ======
def normalize_pagination(args, default_limit=100):
    limit_arg = args.get("limit", str(default_limit))
    if str(limit_arg).lower() == "all":
        return None, 0
    try:
        limit = int(limit_arg)
    except (TypeError, ValueError):
        limit = default_limit
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    return limit, offset

def apply_limit(sql, limit, offset, from_dt=None, to_dt=None):
    if limit is None:
        sql = sql.replace("LIMIT %(limit)s OFFSET %(offset)s", "")
        params = {"from": from_dt, "to": to_dt}
    else:
        params = {"limit": limit, "offset": offset, "from": from_dt, "to": to_dt}
    return sql, params

# ====== Endpoint JSON whitelist ======
@app.get("/query")
def query_json():
    require_key()
    q = request.args.get("q", "now")
    if q not in ALLOWED_QUERIES:
        abort(400, description=f"Query not allowed. Use one of: {', '.join(ALLOWED_QUERIES.keys())}")

    limit, offset = normalize_pagination(request.args)
    from_dt = request.args.get("from")
    to_dt   = request.args.get("to")
    base_sql = ALLOWED_QUERIES[q]
    sql, params = apply_limit(base_sql, limit, offset, from_dt, to_dt)

    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return jsonify(rows)

# ====== Endpoint CSV whitelist ======
@app.get("/query.csv")
def query_csv():
    require_key()
    q = request.args.get("q", "now")
    if q not in ALLOWED_QUERIES:
        abort(400, description=f"Query not allowed. Use one of: {', '.join(ALLOWED_QUERIES.keys())}")

    limit, offset = normalize_pagination(request.args, default_limit=1000)
    from_dt = request.args.get("from")
    to_dt   = request.args.get("to")
    base_sql = ALLOWED_QUERIES[q]
    sql, params = apply_limit(base_sql, limit, offset, from_dt, to_dt)

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)
        writer.writerows(cur.fetchall())
    return Response(buf.getvalue(), mimetype="text/csv")

# ====== Endpoint generic: /table/<tbl>.csv ======
@app.get("/table/<tbl>.csv")
def table_csv(tbl):
    require_key()

    # Chỉ cho phép chữ cái, số, gạch dưới
    if not re.match(r"^[A-Za-z0-9_]+$", tbl):
        abort(400, description="Invalid table name")

    limit, offset = normalize_pagination(request.args, default_limit=1000)

    if limit is None:
        sql = f"SELECT * FROM public.{tbl} ORDER BY 1"
        params = {}
    else:
        sql = f"SELECT * FROM public.{tbl} ORDER BY 1 LIMIT %(limit)s OFFSET %(offset)s"
        params = {"limit": limit, "offset": offset}

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(cols)
        writer.writerows(cur.fetchall())
    return Response(buf.getvalue(), mimetype="text/csv")

# ====== Debug ENV & DB ping ======
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
        socket.getaddrinfo(host, None)
        with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT version() AS version, now() AS now")
            row = cur.fetchone()
        return {"ok": True, "version": row["version"], "now": row["now"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

# ====== Error handling ======
@app.errorhandler(400)
def bad_request(e):
    return jsonify(error=str(e)), 400

@app.errorhandler(401)
def unauthorized(e):
    return jsonify(error=str(e)), 401

@app.errorhandler(500)
def server_error(e):
    return jsonify(error="Internal Server Error"), 500
