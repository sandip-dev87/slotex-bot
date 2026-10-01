"""
Slotex Admin Panel - Flask App
"""
import os
import time
import requests
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify
)
from dotenv import load_dotenv
import turso_serverless

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

app = Flask(__name__)

_original_add_url_rule = app.add_url_rule

def _safe_add_url_rule(rule, endpoint=None, view_func=None, **options):
    resolved_endpoint = endpoint
    if not resolved_endpoint and view_func is not None:
        resolved_endpoint = view_func.__name__
    
    if resolved_endpoint and resolved_endpoint in app.view_functions:
        print(f"[SKIP] Duplicate route: {resolved_endpoint}")
        return
    
    return _original_add_url_rule(rule, endpoint, view_func, **options)

app.add_url_rule = _safe_add_url_rule

app.secret_key = os.getenv("FLASK_SECRET_KEY", "slotex_dev_secret")

TURSO_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
TURSO_API_TOKEN = os.getenv("TURSO_API_TOKEN")
TURSO_ORG = os.getenv("TURSO_ORG_SLUG")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ═════════════════════════════════════════════
# SIMPLE IN-MEMORY CACHE (60 SEC TTL)
# ═════════════════════════════════════════════
import time as _cache_time_mod

_cache_store = {}
_cache_expiry = {}

def cache_get(key):
    if key in _cache_store:
        if _cache_time_mod.time() < _cache_expiry.get(key, 0):
            return _cache_store[key]
        # expired
        _cache_store.pop(key, None)
        _cache_expiry.pop(key, None)
    return None

def cache_set(key, value, ttl=60):
    _cache_store[key] = value
    _cache_expiry[key] = _cache_time_mod.time() + ttl

def cached_query(key, sql, params=(), ttl=60):
    """Run a single-row query with caching."""
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = q_one(sql, params)
    cache_set(key, result, ttl)
    return result

def cached_query_all(key, sql, params=(), ttl=60):
    """Run a multi-row query with caching."""
    cached = cache_get(key)
    if cached is not None:
        return cached
    result = q_all(sql, params)
    cache_set(key, result, ttl)
    return result

PROOF_CHANNEL_ID = os.getenv("PROOF_CHANNEL_ID")


# ═════════════════════════════════════════════
# OPTIMIZED DATABASE HELPERS (with batched queries)
# ═════════════════════════════════════════════
def q_exec(sql, params=()):
    c = turso_serverless.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    try:
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def q_one(sql, params=()):
    c = turso_serverless.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    try:
        return c.execute(sql, params).fetchone()
    finally:
        c.close()


def q_all(sql, params=()):
    c = turso_serverless.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def q_batch(queries):
    """Run multiple queries in ONE connection — 5x faster.
    queries: list of (sql, params) tuples
    Returns: list of results (fetchone or fetchall per query)
    """
    c = turso_serverless.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    try:
        results = []
        for item in queries:
            sql = item[0]
            params = item[1] if len(item) > 1 else ()
            cursor = c.execute(sql, params)
            # Fetch based on query type
            sql_upper = sql.strip().upper()
            if sql_upper.startswith('SELECT'):
                if 'COUNT(' in sql_upper or 'SUM(' in sql_upper or 'MAX(' in sql_upper or 'MIN(' in sql_upper:
                    results.append(cursor.fetchone())
                else:
                    results.append(cursor.fetchall())
            else:
                c.commit()
                results.append(cursor.lastrowid)
        return results
    finally:
        c.close()


def get_setting(key, default=None):
    row = q_one("SELECT value FROM settings WHERE key=?", (key,))
    return row[0] if row else default


def notify_user(tg_id, text):
    if not BOT_TOKEN or not tg_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": tg_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[NOTIFY ERROR] {e}")
        return False


def get_server_metrics():
    m = {"ram_percent": None, "cpu": None, "uptime": None,
         "ram_used_mb": None, "ram_total_mb": None}
    try:
        import psutil
    except ImportError:
        return m
    try:
        ram = psutil.virtual_memory()
        m["ram_percent"] = ram.percent
        m["ram_used_mb"] = round(ram.used / 1024 / 1024, 1)
        m["ram_total_mb"] = round(ram.total / 1024 / 1024, 1)
    except Exception:
        pass
    try:
        m["cpu"] = psutil.cpu_percent(interval=0.3)
    except Exception:
        pass
    try:
        us = time.time() - psutil.boot_time()
        m["uptime"] = f"{int(us // 3600)}h {int((us % 3600) // 60)}m"
    except Exception:
        pass
    return m


def get_turso_usage():
    cached = cache_get("turso_usage")
    if cached is not None:
        return cached
    if not TURSO_API_TOKEN or not TURSO_ORG:
        return None
    try:
        url = f"https://api.turso.tech/v1/organizations/{TURSO_ORG}/usage"
        r = requests.get(url, headers={
            "Authorization": f"Bearer {TURSO_API_TOKEN}"
        }, timeout=5)
        if r.status_code == 200:
            data = r.json()
            org = data.get("organization", {})
            usage = org.get("usage", {})
            result = {
                "rows_read": usage.get("rows_read", 0),
                "rows_written": usage.get("rows_written", 0),
                "storage_bytes": usage.get("storage_bytes", 0),
            }
            cache_set("turso_usage", result, 300)
            return result
    except Exception as e:
        print(f"[TURSO USAGE ERROR] {e}")
    return None


def require_login(f):
    @wraps(f)
    def wrap(*a, **kw):
        if "admin_id" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrap


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        pw = request.form.get("password", "").strip()
        row = q_one("SELECT id, role FROM admins WHERE phone=? AND password=?",
                    (phone, pw))
        if row:
            session["admin_id"] = row[0]
            session["admin_phone"] = phone
            session["admin_role"] = row[1]
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@require_login
def dashboard():
    # Try cached render data
    cached_render = cache_get("dashboard_full")
    if cached_render:
        return cached_render

    now = datetime.utcnow()
    today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    # ─── OPTIMIZED: All queries cached + batched ───
    stats = cache_get("dash_stats")
    if not stats:
        # Try batch first (1 HTTP request for 11 queries)
        try:
            batch = q_batch([
                ("SELECT COUNT(*) FROM users", ()),
                ("SELECT COUNT(*) FROM orders", ()),
                ("SELECT COUNT(*) FROM orders WHERE DATE(created_at)=?", (today,)),
                ("SELECT COUNT(*) FROM orders WHERE DATE(created_at)>=?", (week_ago,)),
                ("SELECT COUNT(*) FROM orders WHERE status='pending'", ()),
                ("SELECT COUNT(*) FROM withdrawals WHERE status='pending'", ()),
                ("SELECT COUNT(*) FROM user_memberships WHERE status='pending'", ()),
                ("SELECT COALESCE(SUM(deposit),0) FROM orders", ()),
                ("SELECT COALESCE(SUM(withdrawal),0) FROM orders", ()),
                ("SELECT COALESCE(SUM(reward),0) FROM orders WHERE status='approved'", ()),
                ("SELECT COALESCE(SUM(commission),0) FROM referrals WHERE status='credited'", ()),
            ])
            stats = {
                "total_users": batch[0][0] if batch[0] else 0,
                "total_orders": batch[1][0] if batch[1] else 0,
                "orders_today": batch[2][0] if batch[2] else 0,
                "orders_week": batch[3][0] if batch[3] else 0,
                "pending_orders": batch[4][0] if batch[4] else 0,
                "pending_withdrawals": batch[5][0] if batch[5] else 0,
                "pending_memberships": batch[6][0] if batch[6] else 0,
                "total_deposit": batch[7][0] if batch[7] else 0,
                "total_withdrawal": batch[8][0] if batch[8] else 0,
                "total_reward": batch[9][0] if batch[9] else 0,
                "total_referral": batch[10][0] if batch[10] else 0,
            }
        except Exception as e:
            print(f"[BATCH FALLBACK] {e}")
            # Fallback to individual queries
            stats = {
                "total_users": q_one("SELECT COUNT(*) FROM users")[0],
                "total_orders": q_one("SELECT COUNT(*) FROM orders")[0],
                "orders_today": q_one("SELECT COUNT(*) FROM orders WHERE DATE(created_at)=?", (today,))[0],
                "orders_week": q_one("SELECT COUNT(*) FROM orders WHERE DATE(created_at)>=?", (week_ago,))[0],
                "pending_orders": q_one("SELECT COUNT(*) FROM orders WHERE status='pending'")[0],
                "pending_withdrawals": q_one("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")[0],
                "pending_memberships": q_one("SELECT COUNT(*) FROM user_memberships WHERE status='pending'")[0],
                "total_deposit": q_one("SELECT COALESCE(SUM(deposit),0) FROM orders")[0],
                "total_withdrawal": q_one("SELECT COALESCE(SUM(withdrawal),0) FROM orders")[0],
                "total_reward": q_one("SELECT COALESCE(SUM(reward),0) FROM orders WHERE status='approved'")[0],
                "total_referral": q_one("SELECT COALESCE(SUM(commission),0) FROM referrals WHERE status='credited'")[0],
            }
        cache_set("dash_stats", stats, 30)  # 5 min

    # ─── Pending lists (cached) ───
    pending_wds = cache_get("dash_pending_wds")
    if not pending_wds:
        pending_wds = q_all(
            "SELECT w.id, u.name, w.amount, w.method, w.details "
            "FROM withdrawals w JOIN users u ON w.user_id=u.id "
            "WHERE w.status='pending' ORDER BY w.id DESC LIMIT 3"
        )
        cache_set("dash_pending_wds", pending_wds, 30)

    pending_mbrs = cache_get("dash_pending_mbrs")
    if not pending_mbrs:
        pending_mbrs = q_all(
            "SELECT um.id, u.name, m.name, um.utr, m.duration_days "
            "FROM user_memberships um "
            "JOIN users u ON um.user_id=u.id "
            "JOIN memberships m ON um.membership_id=m.id "
            "WHERE um.status='pending' ORDER BY um.id DESC LIMIT 3"
        )
        cache_set("dash_pending_mbrs", pending_mbrs, 30)

    pending_ords = cache_get("dash_pending_ords")
    if not pending_ords:
        pending_ords = q_all(
            "SELECT o.id, o.order_no, u.name, o.deposit, o.withdrawal "
            "FROM orders o JOIN users u ON o.user_id=u.id "
            "WHERE o.status='pending' ORDER BY o.id DESC LIMIT 3"
        )
        cache_set("dash_pending_ords", pending_ords, 30)

    daily = cache_get("dash_daily")
    if not daily:
        daily = q_all("""
            SELECT DATE(created_at) as d,
                   COUNT(*) as orders,
                   COALESCE(SUM(deposit),0) as dep,
                   COALESCE(SUM(withdrawal),0) as wd
            FROM orders
            WHERE DATE(created_at) >= ?
            GROUP BY DATE(created_at)
            ORDER BY d
        """, (week_ago,))
        cache_set("dash_daily", daily, 30)

    result = render_template("dashboard.html",
                           stats=stats,
                           pending_wds=pending_wds,
                           pending_mbrs=pending_mbrs,
                           pending_ords=pending_ords,
                           daily=daily,
                           server_metrics=get_server_metrics(),
                           turso_usage=get_turso_usage(),
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))
    cache_set("dashboard_full", result, 30)
    return result


@app.route("/api/withdrawals/<int:wid>/approve", methods=["POST"])
@require_login
def api_wd_approve(wid):
    data = request.get_json() or {}
    notes = data.get("notes", "").strip()
    row = q_one("SELECT user_id, amount FROM withdrawals WHERE id=? AND status='pending'", (wid,))
    if not row:
        return jsonify({"ok": False, "error": "Not found"}), 404
    uid, amount = row
    q_exec("UPDATE withdrawals SET status='approved', notes=? WHERE id=?", (notes, wid))
    urow = q_one("SELECT tg_id FROM users WHERE id=?", (uid,))
    if urow:
        notify_user(urow[0], f"Withdrawal Paid! Amount: Rs {amount:.2f}")
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/withdrawals/<int:wid>/reject", methods=["POST"])
@require_login
def api_wd_reject(wid):
    data = request.get_json() or {}
    reason = data.get("reason", "").strip()
    notes = data.get("notes", "").strip()
    if not reason:
        return jsonify({"ok": False, "error": "Reason required"}), 400
    row = q_one("SELECT user_id, amount, fee FROM withdrawals WHERE id=? AND status='pending'", (wid,))
    if not row:
        return jsonify({"ok": False, "error": "Not found"}), 404
    uid, amount, fee = row
    refund = float(amount) + float(fee)
    q_exec("UPDATE withdrawals SET status='rejected', reason=?, notes=? WHERE id=?", (reason, notes, wid))
    q_exec("UPDATE users SET balance = balance + ? WHERE id=?", (refund, uid))
    urow = q_one("SELECT tg_id FROM users WHERE id=?", (uid,))
    if urow:
        notify_user(urow[0], f"Withdrawal rejected. Reason: {reason}. Refunded: Rs {refund:.2f}")
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/memberships/<int:mid>/approve", methods=["POST"])
@require_login
def api_mbr_approve(mid):
    row = q_one(
        "SELECT um.user_id, um.membership_id, m.duration_days "
        "FROM user_memberships um "
        "JOIN memberships m ON um.membership_id=m.id "
        "WHERE um.id=? AND um.status='pending'",
        (mid,)
    )
    if not row:
        return jsonify({"ok": False, "error": "Not found"}), 404
    uid, plan_id, dur = row
    now = datetime.utcnow()
    expiry = now + timedelta(days=int(dur))
    current = q_one("SELECT membership_expiry FROM users WHERE id=?", (uid,))
    if current and current[0]:
        try:
            old_exp = datetime.fromisoformat(current[0])
            if old_exp > now:
                expiry = old_exp + timedelta(days=int(dur))
        except Exception:
            pass
    q_exec("UPDATE users SET membership_id=?, membership_expiry=? WHERE id=?",
           (plan_id, expiry.isoformat(), uid))
    q_exec("UPDATE user_memberships SET status='approved', expires_at=? WHERE id=?",
           (expiry.isoformat(), mid))
    urow = q_one("SELECT tg_id FROM users WHERE id=?", (uid,))
    if urow:
        notify_user(urow[0], f"Membership approved! Expires: {expiry.strftime('%Y-%m-%d')}")
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/memberships/<int:mid>/reject", methods=["POST"])
@require_login
def api_mbr_reject(mid):
    data = request.get_json() or {}
    reason = data.get("reason", "").strip()
    if not reason:
        return jsonify({"ok": False, "error": "Reason required"}), 400
    row = q_one("SELECT user_id FROM user_memberships WHERE id=? AND status='pending'", (mid,))
    if not row:
        return jsonify({"ok": False, "error": "Not found"}), 404
    uid = row[0]
    q_exec("UPDATE user_memberships SET status='rejected' WHERE id=?", (mid,))
    urow = q_one("SELECT tg_id FROM users WHERE id=?", (uid,))
    if urow:
        notify_user(urow[0], f"Membership rejected. Reason: {reason}")
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/orders/<int:oid>/approve", methods=["POST"])
@require_login
def api_ord_approve(oid):
    data = request.get_json() or {}
    try:
        reward = float(data.get("reward", 0))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Invalid reward"}), 400
    if reward <= 0:
        return jsonify({"ok": False, "error": "Must be positive"}), 400
    row = q_one("SELECT user_id, order_no FROM orders WHERE id=? AND status='pending'", (oid,))
    if not row:
        return jsonify({"ok": False, "error": "Not found"}), 404
    uid, order_no = row
    q_exec("UPDATE orders SET status='approved', reward=? WHERE id=?", (reward, oid))
    q_exec("UPDATE users SET balance = balance + ? WHERE id=?", (reward, uid))
    user_row = q_one("SELECT tg_id, referral_by FROM users WHERE id=?", (uid,))
    if user_row:
        tg_id, ref_acc = user_row
        notify_user(tg_id, f"Order {order_no} approved! Reward Rs {reward:.2f} credited.")
        enabled = get_setting("referral_enabled", "0")
        if enabled == "1" and ref_acc:
            referrer = q_one("SELECT id, tg_id, referral_blocked FROM users WHERE account_no=?", (ref_acc,))
            if referrer:
                ref_id, ref_tg, ref_blocked = referrer
                if ref_blocked:
                    print(f"[REFERRAL BLOCKED] User {ref_id} is blocked, no commission")
                else:
                    commission = float(get_setting("referral_commission", "0"))
                    if commission > 0:
                        q_exec("UPDATE users SET balance = balance + ? WHERE id=?", (commission, ref_id))
                        q_exec(
                            "INSERT INTO referrals(referrer_id, referred_id, order_id, commission, status) "
                            "VALUES(?,?,?,?,'credited')",
                            (ref_id, uid, oid, commission)
                        )
                        notify_user(ref_tg, f"Referral commission Rs {commission:.2f} from {order_no}")
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/orders/<int:oid>/reject", methods=["POST"])
@require_login
def api_ord_reject(oid):
    data = request.get_json() or {}
    reason = data.get("reason", "").strip()
    if not reason:
        return jsonify({"ok": False, "error": "Reason required"}), 400
    row = q_one("SELECT user_id, order_no FROM orders WHERE id=? AND status='pending'", (oid,))
    if not row:
        return jsonify({"ok": False, "error": "Not found"}), 404
    uid, order_no = row
    q_exec("UPDATE orders SET status='rejected', reject_reason=? WHERE id=?", (reason, oid))
    urow = q_one("SELECT tg_id FROM users WHERE id=?", (uid,))
    if urow:
        notify_user(urow[0], f"Order {order_no} rejected. Reason: {reason}")
    cache_clear()
    return jsonify({"ok": True})


# ═════════════════════════════════════════════
# ROUTES — ORDERS PAGE
# ═════════════════════════════════════════════
@app.route("/orders")
@require_login
def orders_page():
    status = request.args.get("status", "all")
    category = request.args.get("category", "all")
    search = request.args.get("search", "").strip()
    date_filter = request.args.get("date", "").strip()

    sql = ("SELECT o.id, o.order_no, u.name, u.mobile, o.category, "
           "o.url, o.deposit, o.withdrawal, o.status, o.reward, o.created_at, "
           "o.deposit_structure, o.instamatch_deposit "
           "FROM orders o JOIN users u ON o.user_id=u.id WHERE 1=1")
    params = []

    if status != "all":
        sql += " AND o.status=?"
        params.append(status)
    if category != "all":
        sql += " AND o.category=?"
        params.append(category)
    if search:
        sql += " AND (o.order_no LIKE ? OR u.name LIKE ? OR u.mobile LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    if date_filter:
        sql += " AND DATE(o.created_at)=?"
        params.append(date_filter)

    sql += " ORDER BY o.id DESC LIMIT 200"
    orders = q_all(sql, tuple(params))

    return render_template("orders.html",
                           orders=orders,
                           status=status,
                           category=category,
                           search=search,
                           date_filter=date_filter,
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


@app.route("/orders/<int:oid>")
@require_login
def order_detail(oid):
    row = q_one(
        "SELECT o.id, o.order_no, o.user_id, o.category, o.url, o.game_uid, "
        "o.deposit, o.withdrawal, o.proof_deposit, o.proof_withdrawal, "
        "o.proof_stat, o.status, o.reward, o.reject_reason, o.created_at, "
        "u.name, u.mobile, u.account_no, u.tg_id, o.deposit_structure, o.instamatch_deposit "
        "FROM orders o JOIN users u ON o.user_id=u.id WHERE o.id=?",
        (oid,)
    )
    if not row:
        return "Order not found", 404

    order = {
        "id": row[0], "order_no": row[1], "user_id": row[2],
        "category": row[3], "url": row[4], "game_uid": row[5],
        "deposit": row[6], "withdrawal": row[7],
        "proof_deposit": row[8], "proof_withdrawal": row[9], "proof_stat": row[10],
        "status": row[11], "reward": row[12], "reject_reason": row[13],
        "created_at": row[14],
        "user_name": row[15], "user_mobile": row[16],
        "user_account": row[17], "user_tg": row[18],
        "deposit_structure": row[19] if len(row) > 19 else "",
        "instamatch_deposit": row[20] if len(row) > 20 else 0
    }

    return render_template("order_detail.html",
                           order=order,
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


@app.route("/proof/<path:file_id>")
@require_login
def proof_image(file_id):
    """Proxy route to serve Telegram proof images."""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return "File not found", 404
        data = r.json()
        if not data.get("ok"):
            return "File error", 404
        file_path = data["result"]["file_path"]

        img_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        img = requests.get(img_url, timeout=10)
        if img.status_code != 200:
            return "Image error", 404

        from flask import Response
        return Response(img.content, mimetype="image/jpeg")
    except Exception as e:
        print(f"[PROOF ERROR] {e}")
        return "Error", 500


# ═════════════════════════════════════════════
# ROUTES — USERS PAGE
# ═════════════════════════════════════════════
@app.route("/users")
@require_login
def users_page():
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "all")

    sql = ("SELECT id, name, mobile, account_no, tg_id, balance, "
           "membership_expiry, is_banned, created_at FROM users WHERE 1=1")
    params = []

    if search:
        sql += " AND (name LIKE ? OR mobile LIKE ? OR account_no LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    if status == "banned":
        sql += " AND is_banned=1"
    elif status == "active":
        sql += " AND is_banned=0"

    optimized_sql = """SELECT u.id, u.name, u.mobile, u.account_no, u.tg_id, u.balance,
                       u.membership_expiry, u.is_banned, u.created_at,
                       COUNT(o.id) as orders_count,
                       SUM(CASE WHEN o.status='approved' THEN 1 ELSE 0 END) as approved_count
                FROM users u
                LEFT JOIN orders o ON o.user_id = u.id
                WHERE 1=1"""

    if search:
        optimized_sql += " AND (u.name LIKE ? OR u.mobile LIKE ? OR u.account_no LIKE ?)"
    if status == "banned":
        optimized_sql += " AND u.is_banned=1"
    elif status == "active":
        optimized_sql += " AND u.is_banned=0"

    optimized_sql += " GROUP BY u.id ORDER BY u.id DESC LIMIT 200"

    rows = q_all(optimized_sql, tuple(params))

    users = []
    for r in rows:
        users.append({
            "id": r[0], "name": r[1], "mobile": r[2], "account_no": r[3],
            "tg_id": r[4], "balance": r[5], "membership_expiry": r[6],
            "is_banned": r[7], "created_at": r[8],
            "orders_count": r[9] or 0, "approved_count": r[10] or 0
        })

    return render_template("users.html",
                           users=users,
                           search=search,
                           status=status,
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


@app.route("/users/<int:uid>")
@require_login
def user_detail(uid):
    row = q_one("SELECT id, name, mobile, account_no, tg_id, balance, "
                "referral_by, membership_expiry, is_banned, created_at "
                "FROM users WHERE id=?", (uid,))
    if not row:
        return "User not found", 404

    user = {
        "id": row[0], "name": row[1], "mobile": row[2], "account_no": row[3],
        "tg_id": row[4], "balance": row[5], "referral_by": row[6],
        "membership_expiry": row[7], "is_banned": row[8], "created_at": row[9]
    }

    # Stats
    total_orders = q_one("SELECT COUNT(*) FROM orders WHERE user_id=?", (uid,))[0]
    approved_orders = q_one("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='approved'", (uid,))[0]
    total_deposit = q_one("SELECT COALESCE(SUM(deposit),0) FROM orders WHERE user_id=?", (uid,))[0]
    total_withdrawal = q_one("SELECT COALESCE(SUM(withdrawal),0) FROM orders WHERE user_id=?", (uid,))[0]
    total_reward = q_one("SELECT COALESCE(SUM(reward),0) FROM orders WHERE user_id=? AND status='approved'", (uid,))[0]

    # Order history
    orders = q_all(
        "SELECT id, order_no, category, deposit, withdrawal, reward, status, created_at "
        "FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,)
    )

    # Referral list (jinko is user ne refer kiya)
    referrals = q_all(
        "SELECT u.id, u.name, u.account_no, "
        "(SELECT COUNT(*) FROM orders WHERE user_id=u.id AND status='approved') as cnt, "
        "(SELECT COALESCE(SUM(commission),0) FROM referrals WHERE referrer_id=? AND referred_id=u.id AND status='credited') as comm "
        "FROM users u WHERE u.referral_by=? ORDER BY u.id DESC LIMIT 20",
        (uid, user["account_no"])
    )

    # Total referral earnings
    referral_total = q_one(
        "SELECT COALESCE(SUM(commission),0) FROM referrals WHERE referrer_id=? AND status='credited'",
        (uid,)
    )[0]

    return render_template("user_detail.html",
                           user=user,
                           stats={
                               "total_orders": total_orders,
                               "approved_orders": approved_orders,
                               "total_deposit": total_deposit,
                               "total_withdrawal": total_withdrawal,
                               "total_reward": total_reward,
                           },
                           orders=orders,
                           referrals=referrals,
                           referral_total=referral_total,
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


@app.route("/api/users/<int:uid>/ban", methods=["POST"])
@require_login
def api_user_ban(uid):
    q_exec("UPDATE users SET is_banned=1 WHERE id=?", (uid,))
    urow = q_one("SELECT tg_id FROM users WHERE id=?", (uid,))
    if urow:
        notify_user(urow[0], "🚫 Your account has been banned. Contact support.")
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/users/<int:uid>/unban", methods=["POST"])
@require_login
def api_user_unban(uid):
    q_exec("UPDATE users SET is_banned=0 WHERE id=?", (uid,))
    urow = q_one("SELECT tg_id FROM users WHERE id=?", (uid,))
    if urow:
        notify_user(urow[0], "✅ Your account has been unbanned.")
    cache_clear()
    return jsonify({"ok": True})


# ═════════════════════════════════════════════
# ═════════════════════════════════════════════
# ROUTES — WITHDRAWALS PAGE
# ═════════════════════════════════════════════
@app.route("/withdrawals")
@require_login
def withdrawals_page():
    status = request.args.get("status", "all")
    method = request.args.get("method", "all")
    search = request.args.get("search", "").strip()
    date_filter = request.args.get("date", "").strip()

    sql = ("SELECT w.id, w.user_id, u.name, u.mobile, w.method, w.amount, w.fee, "
           "w.details, w.status, w.reason, w.created_at, w.notes "
           "FROM withdrawals w JOIN users u ON w.user_id=u.id WHERE 1=1")
    params = []

    if status != "all":
        sql += " AND w.status=?"
        params.append(status)
    if method != "all":
        sql += " AND w.method=?"
        params.append(method)
    if search:
        sql += " AND (u.name LIKE ? OR u.mobile LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])
    if date_filter:
        sql += " AND DATE(w.created_at)=?"
        params.append(date_filter)

    sql += " ORDER BY w.id DESC LIMIT 200"
    rows = q_all(sql, tuple(params))

    return render_template("withdrawals.html",
                           withdrawals=rows,
                           status=status, method=method, search=search,
                           date_filter=date_filter,
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


# ═════════════════════════════════════════════
# ═════════════════════════════════════════════
# ROUTES — MEMBERSHIPS PAGE
# ═════════════════════════════════════════════
@app.route("/memberships")
@require_login
def memberships_page():
    tab = request.args.get("tab", "requests")

    plans = q_all("SELECT id, name, price, duration_days, is_active FROM memberships ORDER BY id DESC")

    status = request.args.get("status", "pending")
    sql = ("SELECT um.id, um.user_id, u.name, u.mobile, m.name, m.duration_days, "
           "m.price, um.utr, um.status, um.starts_at, um.expires_at "
           "FROM user_memberships um "
           "JOIN users u ON um.user_id=u.id "
           "JOIN memberships m ON um.membership_id=m.id WHERE 1=1")
    params = []
    if status != "all":
        sql += " AND um.status=?"
        params.append(status)
    sql += " ORDER BY um.id DESC LIMIT 100"
    requests = q_all(sql, tuple(params))

    return render_template("memberships.html",
                           plans=plans, requests=requests,
                           tab=tab, status=status,
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


@app.route("/api/plans/create", methods=["POST"])
@require_login
def api_plan_create():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    try:
        price = float(data.get("price", 0))
        duration = int(data.get("duration", 0))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Invalid price/duration"}), 400

    if not name or duration <= 0:
        return jsonify({"ok": False, "error": "Name and duration required"}), 400

    q_exec("INSERT INTO memberships(name, price, duration_days, is_active) VALUES (?,?,?,1)",
           (name, price, duration))
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/plans/<int:pid>/update", methods=["POST"])
@require_login
def api_plan_update(pid):
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    try:
        price = float(data.get("price", 0))
        duration = int(data.get("duration", 0))
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Invalid"}), 400

    if not name or duration <= 0:
        return jsonify({"ok": False, "error": "Invalid fields"}), 400

    q_exec("UPDATE memberships SET name=?, price=?, duration_days=? WHERE id=?",
           (name, price, duration, pid))
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/plans/<int:pid>/delete", methods=["POST"])
@require_login
def api_plan_delete(pid):
    q_exec("DELETE FROM memberships WHERE id=?", (pid,))
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/plans/<int:pid>/toggle", methods=["POST"])
@require_login
def api_plan_toggle(pid):
    row = q_one("SELECT is_active FROM memberships WHERE id=?", (pid,))
    if not row:
        return jsonify({"ok": False, "error": "Not found"}), 404
    new_val = 0 if row[0] else 1
    q_exec("UPDATE memberships SET is_active=? WHERE id=?", (new_val, pid))
    return jsonify({"ok": True, "is_active": new_val})


# ═════════════════════════════════════════════
# ROUTES — URLS ANALYTICS
# ═════════════════════════════════════════════
@app.route("/urls")
@require_login
def urls_page():
    mode = request.args.get("mode", "url_date")
    search = request.args.get("search", "").strip()
    expand_url = request.args.get("expand", "").strip()
    expand_date = request.args.get("expand_date", "").strip()

    # ─── SUMMARY LIST ───
    if mode == "url":
        sql = ("""SELECT url,
                         COUNT(*) as total_orders,
                         COALESCE(SUM(deposit),0) as total_deposit,
                         COALESCE(SUM(withdrawal),0) as total_withdrawal,
                         COALESCE(SUM(reward),0) as total_reward
                  FROM orders WHERE url IS NOT NULL AND url != ''""")
        params = []
        if search:
            sql += " AND url LIKE ?"
            params.append(f"%{search}%")
        sql += " GROUP BY url ORDER BY total_orders DESC LIMIT 200"
        rows = q_all(sql, tuple(params))

        # OPTIMIZED: Get users/uids/pending in ONE query
        urls_data = []
        for r in rows:
            url = r[0]
            extra = q_one("""
                SELECT COUNT(DISTINCT user_id) as users,
                       COUNT(DISTINCT CASE WHEN game_uid IS NOT NULL AND game_uid != '' THEN game_uid END) as uids,
                       SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending
                FROM orders WHERE url=?
            """, (url,))
            users_cnt = extra[0] if extra else 0
            uids_cnt = extra[1] if extra else 0
            pending_cnt = extra[2] if extra and extra[2] else 0

            urls_data.append({
                "url": url, "date": None,
                "orders": r[1], "deposit": r[2], "withdrawal": r[3], "reward": r[4],
                "users": users_cnt, "uids": uids_cnt, "pending": pending_cnt
            })
    else:
        sql = ("""SELECT url, DATE(created_at) as d,
                         COUNT(*) as total_orders,
                         COALESCE(SUM(deposit),0) as total_deposit,
                         COALESCE(SUM(withdrawal),0) as total_withdrawal,
                         COALESCE(SUM(reward),0) as total_reward
                  FROM orders WHERE url IS NOT NULL AND url != ''""")
        params = []
        if search:
            sql += " AND url LIKE ?"
            params.append(f"%{search}%")
        sql += " GROUP BY url, DATE(created_at) ORDER BY d DESC, total_orders DESC LIMIT 200"
        rows = q_all(sql, tuple(params))

        # OPTIMIZED: 3 queries → 1
        urls_data = []
        for r in rows:
            url, date = r[0], r[1]
            extra = q_one("""
                SELECT COUNT(DISTINCT user_id) as users,
                       COUNT(DISTINCT CASE WHEN game_uid IS NOT NULL AND game_uid != '' THEN game_uid END) as uids,
                       SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending
                FROM orders WHERE url=? AND DATE(created_at)=?
            """, (url, date))
            users_cnt = extra[0] if extra else 0
            uids_cnt = extra[1] if extra else 0
            pending_cnt = extra[2] if extra and extra[2] else 0

            urls_data.append({
                "url": url, "date": date,
                "orders": r[2], "deposit": r[3], "withdrawal": r[4], "reward": r[5],
                "users": users_cnt, "uids": uids_cnt, "pending": pending_cnt
            })

    # ─── EXPANDED VIEW ───
    expand_data = None
    expand_users = []

    if expand_url:
        if expand_date:
            user_rows = q_all(
                """SELECT u.id, u.name, u.mobile, u.account_no,
                          COUNT(o.id) as orders_cnt,
                          SUM(CASE WHEN o.status='approved' THEN 1 ELSE 0 END) as approved_cnt,
                          SUM(CASE WHEN o.status='pending' THEN 1 ELSE 0 END) as pending_cnt,
                          SUM(CASE WHEN o.status='rejected' THEN 1 ELSE 0 END) as rejected_cnt,
                          COALESCE(SUM(o.deposit),0) as total_dep,
                          COALESCE(SUM(o.withdrawal),0) as total_wd,
                          COALESCE(SUM(o.reward),0) as total_rw
                   FROM orders o
                   JOIN users u ON o.user_id = u.id
                   WHERE o.url = ? AND DATE(o.created_at) = ?
                   GROUP BY u.id
                   ORDER BY total_dep DESC""",
                (expand_url, expand_date)
            )
            where_date = " AND DATE(created_at)=?"
            date_params = (expand_date,)
        else:
            user_rows = q_all(
                """SELECT u.id, u.name, u.mobile, u.account_no,
                          COUNT(o.id) as orders_cnt,
                          SUM(CASE WHEN o.status='approved' THEN 1 ELSE 0 END) as approved_cnt,
                          SUM(CASE WHEN o.status='pending' THEN 1 ELSE 0 END) as pending_cnt,
                          SUM(CASE WHEN o.status='rejected' THEN 1 ELSE 0 END) as rejected_cnt,
                          COALESCE(SUM(o.deposit),0) as total_dep,
                          COALESCE(SUM(o.withdrawal),0) as total_wd,
                          COALESCE(SUM(o.reward),0) as total_rw
                   FROM orders o
                   JOIN users u ON o.user_id = u.id
                   WHERE o.url = ?
                   GROUP BY u.id
                   ORDER BY total_dep DESC""",
                (expand_url,)
            )
            where_date = ""
            date_params = ()

        for row in user_rows:
            uid = row[0]
            user_uids = q_all(
                "SELECT DISTINCT game_uid FROM orders WHERE user_id=? AND url=?" + where_date +
                " AND game_uid IS NOT NULL AND game_uid != ''",
                (uid, expand_url) + date_params
            )
            expand_users.append({
                "id": row[0], "name": row[1], "mobile": row[2], "account_no": row[3],
                "orders": row[4], "approved": row[5], "pending": row[6], "rejected": row[7],
                "deposit": row[8], "withdrawal": row[9], "reward": row[10],
                "uids": [u[0] for u in user_uids]
            })

        # All UIDs for this URL
        all_uids = q_all(
            "SELECT DISTINCT game_uid FROM orders WHERE url=?" + where_date +
            " AND game_uid IS NOT NULL AND game_uid != ''",
            (expand_url,) + date_params
        )
        pending_uids = q_all(
            "SELECT DISTINCT game_uid FROM orders WHERE url=? AND status='pending'" + where_date +
            " AND game_uid IS NOT NULL AND game_uid != ''",
            (expand_url,) + date_params
        )

        # Total stats
        total_orders_cnt = sum(u["orders"] for u in expand_users)
        total_dep = sum(u["deposit"] for u in expand_users)
        total_wd = sum(u["withdrawal"] for u in expand_users)
        total_reward = sum(u["reward"] for u in expand_users)
        total_pending = sum(u["pending"] for u in expand_users)

        expand_data = {
            "url": expand_url, "date": expand_date or None,
            "total_orders": total_orders_cnt,
            "total_dep": total_dep, "total_wd": total_wd,
            "total_reward": total_reward,
            "total_pending": total_pending,
            "all_uids": [u[0] for u in all_uids],
            "pending_uids": [u[0] for u in pending_uids]
        }

    return render_template("urls.html",
                           urls_data=urls_data, mode=mode, search=search,
                           expand_url=expand_url, expand_date=expand_date,
                           expand_data=expand_data, expand_users=expand_users,
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


# ═════════════════════════════════════════════
# ROUTES — SETTINGS PAGE
# ═════════════════════════════════════════════
@app.route("/settings")
@require_login
def settings_page():
    settings = {}
    rows = q_all("SELECT key, value FROM settings")
    for k, v in rows:
        settings[k] = v

    return render_template("settings.html",
                           settings=settings,
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


@app.route("/api/settings/save", methods=["POST"])
@require_login
def api_settings_save():
    data = request.get_json() or {}
    allowed = [
        "fee_crypto", "fee_upi", "fee_bank",
        "min_deposit", "min_withdrawal",
        "referral_commission", "referral_enabled",
        "support_text",
        "buy_link",
    ]
    for key in allowed:
        if key in data:
            q_exec(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(data[key]))
            )
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/settings/upload_qr", methods=["POST"])
@require_login
def api_upload_qr():
    return _upload_media("qr_code_file_id")


@app.route("/api/settings/upload_banner", methods=["POST"])
@require_login
def api_upload_banner():
    return _upload_media("referral_banner_file_id")


def _upload_media(setting_key):
    """Generic image upload handler."""
    if "image" not in request.files:
        return jsonify({"ok": False, "error": "No file"}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400

    try:
        files = {
            "photo": (file.filename, file.stream, file.content_type or "image/jpeg")
        }
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": PROOF_CHANNEL_ID or ""},
            files=files,
            timeout=30
        )
        if r.status_code != 200:
            return jsonify({"ok": False, "error": f"Telegram error {r.status_code}"}), 400

        resp = r.json()
        if not resp.get("ok"):
            return jsonify({"ok": False, "error": "Telegram rejected"}), 400

        # Get file_id
        file_id = resp["result"]["photo"][-1]["file_id"]

        # Save to settings
        q_exec(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (setting_key, file_id)
        )

        return jsonify({"ok": True, "file_id": file_id})
    except Exception as e:
        print(f"[UPLOAD ERROR] {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ═════════════════════════════════════════════
# ROUTES — ADMINS MANAGEMENT
# ═════════════════════════════════════════════
def require_super_admin(f):
    from functools import wraps as _wraps
    @_wraps(f)
    def wrap(*a, **kw):
        if session.get("admin_role") != "super":
            return "Super Admin only", 403
        return f(*a, **kw)
    return wrap


@app.route("/admins")
@require_login
@require_super_admin
def admins_page():
    admins = q_all("SELECT id, phone, role FROM admins ORDER BY id ASC")
    return render_template("admins.html",
                           admins=admins,
                           current_id=session.get("admin_id"),
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


@app.route("/api/admins/create", methods=["POST"])
@require_login
@require_super_admin
def api_admin_create():
    data = request.get_json() or {}
    phone = data.get("phone", "").strip()
    password = data.get("password", "").strip()
    role = data.get("role", "normal").strip()

    if not (phone.isdigit() and len(phone) == 10):
        return jsonify({"ok": False, "error": "Phone must be 10 digits"}), 400
    if len(password) < 4:
        return jsonify({"ok": False, "error": "Password min 4 chars"}), 400
    if role not in ("super", "normal"):
        return jsonify({"ok": False, "error": "Invalid role"}), 400

    # Check duplicate phone
    if q_one("SELECT 1 FROM admins WHERE phone=?", (phone,)):
        return jsonify({"ok": False, "error": "Phone already exists"}), 400

    q_exec("INSERT INTO admins(phone, password, role) VALUES (?,?,?)",
           (phone, password, role))
    cache_clear()
    return jsonify({"ok": True})


# ═════════════════════════════════════════════
# RUN
# ═════════════════════════════════════════════
# ═════════════════════════════════════════════
# ROUTES — REFERRAL MANAGEMENT
# ═════════════════════════════════════════════
@app.route("/referrals")
@require_login
def referrals_page():
    search = request.args.get("search", "").strip()
    referrer_filter = request.args.get("referrer", "").strip()

    sql = """SELECT u.id, u.name, u.account_no, u.referral_by,
                    u.referral_blocked,
                    COALESCE(
                        (SELECT COUNT(*) FROM users u2 WHERE u2.referral_by = u.account_no),
                        0
                    ) as ref_count,
                    COALESCE(
                        (SELECT SUM(commission) FROM referrals WHERE referrer_id = u.id AND status='credited'),
                        0
                    ) as total_earned
             FROM users u WHERE 1=1"""
    params = []

    if referrer_filter:
        sql += " AND u.referral_by = ?"
        params.append(referrer_filter)
    elif search:
        sql += " AND (u.name LIKE ? OR u.mobile LIKE ? OR u.account_no LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])

    sql += " ORDER BY ref_count DESC, u.id DESC LIMIT 500"

    rows = q_all(sql, tuple(params))

    users_data = []
    for r in rows:
        users_data.append({
            "id": r[0], "name": r[1], "account_no": r[2],
            "referral_by": r[3], "blocked": r[4],
            "ref_count": r[5], "earned": r[6]
        })

    # Get all referrer account numbers (for filter dropdown)
    referrers = q_all(
        "SELECT DISTINCT u.account_no, u.name FROM users u "
        "WHERE EXISTS (SELECT 1 FROM users u2 WHERE u2.referral_by = u.account_no) "
        "ORDER BY u.id DESC LIMIT 100"
    )

    # Stats
    total_referrals = q_one("SELECT COUNT(*) FROM users WHERE referral_by IS NOT NULL")[0]
    total_commission = q_one("SELECT COALESCE(SUM(commission),0) FROM referrals WHERE status='credited'")[0]
    total_blocked = q_one("SELECT COUNT(*) FROM users WHERE referral_blocked=1")[0]

    return render_template("referrals.html",
                           users_data=users_data,
                           referrers=referrers,
                           search=search,
                           referrer_filter=referrer_filter,
                           stats={
                               "total_referrals": total_referrals,
                               "total_commission": total_commission,
                               "total_blocked": total_blocked,
                           },
                           admin_phone=session.get("admin_phone"),
                           admin_role=session.get("admin_role"))


@app.route("/api/users/<int:uid>/block_referral", methods=["POST"])
@require_login
def api_block_referral(uid):
    q_exec("UPDATE users SET referral_blocked=1 WHERE id=?", (uid,))
    cache_clear()
    return jsonify({"ok": True})


@app.route("/api/users/<int:uid>/unblock_referral", methods=["POST"])
@require_login
def api_unblock_referral(uid):
    q_exec("UPDATE users SET referral_blocked=0 WHERE id=?", (uid,))
    cache_clear()
    return jsonify({"ok": True})


if __name__ == "__main__":
    import os as _os
    port = int(_os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
