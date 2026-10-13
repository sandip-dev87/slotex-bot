"""
Local SQLite replica — fast reads ke liye.
Turso se background me sync hoti hai.
"""
import os
import sqlite3
import threading
import time

SYNC_TABLES = [
    "users", "orders", "withdrawals", "referrals", "settings",
    "admins", "memberships", "user_memberships", "otp_codes", "balance_history",
]

_local_conn = None
_sync_running = False
_turso_url = None
_turso_token = None
_db_lock = threading.Lock()

LOCAL_DB_PATH = os.path.join(os.path.dirname(__file__), "local_replica.db")


def _get_table_schemas():
    import turso_serverless
    conn = turso_serverless.connect(_turso_url, auth_token=_turso_token)
    cur = conn.cursor()
    schemas = {}
    for tbl in SYNC_TABLES:
        try:
            cur.execute(f"PRAGMA table_info({tbl})")
            cols = [c[1] for c in cur.fetchall()]
            if cols:
                schemas[tbl] = cols
        except Exception as e:
            print(f"[local_db] schema error {tbl}: {e}")
    return schemas


def _create_local_tables(schemas):
    for tbl, cols in schemas.items():
        cols_sql = ", ".join([f'"{c}"' for c in cols])
        _local_conn.execute(f'CREATE TABLE IF NOT EXISTS "{tbl}" ({cols_sql})')
    _local_conn.commit()


def _full_sync():
    import turso_serverless
    t0 = time.time()
    schemas = _get_table_schemas()
    if not schemas:
        return False
    _create_local_tables(schemas)

    remote = turso_serverless.connect(_turso_url, auth_token=_turso_token)
    rcur = remote.cursor()

    with _db_lock:
        for tbl, cols in schemas.items():
            try:
                rcur.execute(f'SELECT * FROM "{tbl}"')
                rows = rcur.fetchall()
            except Exception as e:
                print(f"[local_db] fetch {tbl}: {e}")
                continue
            _local_conn.execute(f'DELETE FROM "{tbl}"')
            if rows:
                ph = ",".join(["?"] * len(cols))
                _local_conn.executemany(f'INSERT INTO "{tbl}" VALUES ({ph})', rows)
        _local_conn.commit()

    print(f"[local_db] synced in {time.time()-t0:.2f}s")
    return True


def _sync_loop(interval=60):
    while _sync_running:
        time.sleep(interval)
        try:
            _full_sync()
        except Exception as e:
            print(f"[local_db] sync error: {e}")


def init_local_db(turso_url, turso_token, sync_interval=60):
    global _local_conn, _sync_running, _turso_url, _turso_token
    _turso_url = turso_url
    _turso_token = turso_token

    try:
        _local_conn = sqlite3.connect(LOCAL_DB_PATH, check_same_thread=False)
        _local_conn.execute("PRAGMA journal_mode=WAL")
        _local_conn.execute("PRAGMA synchronous=NORMAL")
    except Exception as e:
        print(f"[local_db] init error: {e}")
        return False

    if not _full_sync():
        return False

    _sync_running = True
    threading.Thread(target=_sync_loop, args=(sync_interval,), daemon=True).start()
    print(f"[local_db] Background sync started ({sync_interval}s)")
    return True


def local_q_all(sql, params=()):
    try:
        with _db_lock:
            cur = _local_conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
        print(f"[local_db] q_all error: {e} | SQL: {sql[:80]}")
        return []


def local_q_one(sql, params=()):
    rows = local_q_all(sql, params)
    return rows[0] if rows else None


def local_q_exec(sql, params=()):
    try:
        with _db_lock:
            cur = _local_conn.cursor()
            cur.execute(sql, params)
            _local_conn.commit()
        return True
    except Exception as e:
        print(f"[local_db] q_exec error: {e} | SQL: {sql[:80]}")
        return False
