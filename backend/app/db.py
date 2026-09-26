import os
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

DB_CREDENTIALS = {
    "admin":  (os.getenv("DB_USER_ADMIN", "club_admin"),   os.getenv("DB_PASS_ADMIN", "admin_pass")),
    "host":   (os.getenv("DB_USER_HOST", "club_host"),     os.getenv("DB_PASS_HOST", "host_pass")),
    "viewer": (os.getenv("DB_USER_VIEWER", "club_viewer"), os.getenv("DB_PASS_VIEWER", "viewer_pass")),
}


def connect(role: str) -> pymysql.Connection:
    user, password = DB_CREDENTIALS[role]
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME", "board_club"),
        user=user,
        password=password,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )


@contextmanager
def get_db(role: str):
    conn = connect(role)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: pymysql.Connection):
    conn.begin()
    try:
        yield conn.cursor()
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def fetch_all(conn, sql: str, params=None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(conn, sql: str, params=None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(conn, sql: str, params=None) -> pymysql.cursors.Cursor:
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def paginate(conn, select: str, where: list[str], params: list, order: str, page: int, size: int) -> dict:
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    total = fetch_one(conn, f"SELECT COUNT(*) AS n FROM ({select}{where_sql}) t", params)["n"]
    items = fetch_all(conn, f"{select}{where_sql} ORDER BY {order} LIMIT %s OFFSET %s",
                      [*params, size, (page - 1) * size])
    return {"items": items, "total": total, "page": page, "size": size}