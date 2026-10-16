"""
Migrate all data from Turso (SQLite) to RamNaym MySQL.
Run this in Termux (has both Turso + network access).
"""
import os
from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/slotex-bot/.env"))

import turso_serverless
import pymysql

# Turso connection
t_conn = turso_serverless.connect(
    os.getenv("TURSO_DATABASE_URL"),
    auth_token=os.getenv("TURSO_AUTH_TOKEN")
)
t_cur = t_conn.cursor()

# MySQL connection (use RamNaym creds)
m_conn = pymysql.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DATABASE"),
    port=int(os.getenv("MYSQL_PORT", 3306)),
    charset="utf8mb4"
)
m_cur = m_conn.cursor()

# MySQL schema
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        tg_id VARCHAR(50) NOT NULL,
        name VARCHAR(255) NOT NULL,
        mobile VARCHAR(20) NOT NULL,
        password VARCHAR(255) NOT NULL,
        account_no VARCHAR(20) UNIQUE NOT NULL,
        balance DECIMAL(12,2) DEFAULT 0,
        referral_by VARCHAR(20),
        membership_id INT,
        membership_expiry VARCHAR(30),
        is_banned TINYINT DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_users_tg (tg_id),
        INDEX idx_users_mobile (mobile),
        INDEX idx_users_account (account_no)
    )""",
    """CREATE TABLE IF NOT EXISTS memberships (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        price DECIMAL(12,2) DEFAULT 0,
        duration_days INT NOT NULL,
        is_active TINYINT DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS user_memberships (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        membership_id INT NOT NULL,
        starts_at VARCHAR(30),
        expires_at VARCHAR(30),
        status VARCHAR(20) DEFAULT 'pending',
        utr VARCHAR(255),
        reject_reason TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS orders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        order_no VARCHAR(20) UNIQUE NOT NULL,
        user_id INT NOT NULL,
        category VARCHAR(50) NOT NULL,
        url TEXT,
        game_uid VARCHAR(50),
        acc_pass VARCHAR(100) DEFAULT '',
        game_mobile VARCHAR(20) DEFAULT '',
        deposit DECIMAL(12,2) DEFAULT 0,
        withdrawal DECIMAL(12,2) DEFAULT 0,
        proof_deposit TEXT,
        proof_withdrawal TEXT,
        proof_stat TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        reward DECIMAL(12,2) DEFAULT 0,
        reject_reason TEXT,
        deposit_structure VARCHAR(255) DEFAULT '',
        instamatch_deposit DECIMAL(12,2) DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_orders_user (user_id),
        INDEX idx_orders_status (status),
        INDEX idx_orders_uid (game_uid)
    )""",
    """CREATE TABLE IF NOT EXISTS withdrawals (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        method VARCHAR(20) NOT NULL,
        amount DECIMAL(12,2) NOT NULL,
        fee DECIMAL(12,2) DEFAULT 0,
        details TEXT,
        qr_proof TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        reason TEXT,
        notes TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_wd_user (user_id),
        INDEX idx_wd_status (status)
    )""",
    """CREATE TABLE IF NOT EXISTS referrals (
        id INT AUTO_INCREMENT PRIMARY KEY,
        referrer_id INT NOT NULL,
        referred_id INT NOT NULL,
        order_id INT,
        commission DECIMAL(12,2) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'pending',
        credited_at VARCHAR(30),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS settings (
        `key` VARCHAR(100) PRIMARY KEY,
        value TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS admins (
        id INT AUTO_INCREMENT PRIMARY KEY,
        phone VARCHAR(20) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        role VARCHAR(20) DEFAULT 'normal',
        can_access_settings TINYINT DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS otp_codes (
        mobile VARCHAR(20) PRIMARY KEY,
        otp VARCHAR(10) NOT NULL,
        expires_at VARCHAR(30) NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS balance_history (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        type VARCHAR(30),
        amount DECIMAL(12,2),
        balance_before DECIMAL(12,2),
        balance_after DECIMAL(12,2),
        reason TEXT,
        admin_id INT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_bh_user (user_id)
    )""",
]

print("Creating tables in MySQL...")
for ddl in SCHEMA:
    try:
        m_cur.execute(ddl)
        m_conn.commit()
    except Exception as e:
        print(f"  DDL skip: {e}")
print("Tables created.")

# Settings defaults
DEFAULTS = [
    ('fee_crypto','5'),('fee_upi','3'),('fee_bank','4'),
    ('min_withdrawal','100'),('min_deposit','50'),
    ('referral_commission','20'),('referral_enabled','1'),
    ('qr_code_file_id',''),('referral_banner_file_id',''),('referral_banner_text',''),
]
for k, v in DEFAULTS:
    try:
        m_cur.execute("INSERT IGNORE INTO settings(`key`, value) VALUES (%s, %s)", (k, v))
    except Exception:
        pass
m_conn.commit()
print("Settings defaults inserted.")

# ─── Copy tables ───
TABLES = [
    "users", "orders", "withdrawals", "referrals", "settings",
    "admins", "memberships", "user_memberships", "otp_codes", "balance_history"
]

for tbl in TABLES:
    print(f"\n=== {tbl} ===")
    try:
        t_cur.execute(f"SELECT * FROM {tbl}")
        rows = t_cur.fetchall()
    except Exception as e:
        print(f"  Turso fetch failed: {e}")
        continue

    if not rows:
        print("  No rows")
        continue

    # Get column names from Turso
    t_cur.execute(f"PRAGMA table_info({tbl})")
    t_cols = [c[1] for c in t_cur.fetchall()]

    # Get MySQL columns (excluding id for auto)
    m_cur.execute(f"SHOW COLUMNS FROM {tbl}")
    m_cols = [c[0] for c in m_cur.fetchall()]

    # Use only common columns
    cols = [c for c in t_cols if c in m_cols]
    print(f"  Copying {len(rows)} rows, cols: {cols}")

    placeholders = ",".join(["%s"] * len(cols))
    col_names = ",".join([f"`{c}`" for c in cols])
    insert_sql = f"INSERT IGNORE INTO {tbl} ({col_names}) VALUES ({placeholders})"

    inserted = 0
    for row in rows:
        vals = []
        for i, c in enumerate(t_cols):
            if c in cols:
                vals.append(row[i])
        try:
            m_cur.execute(insert_sql, tuple(vals))
            inserted += 1
        except Exception as e:
            print(f"  Row insert error: {e}")
            break
    m_conn.commit()
    print(f"  Inserted: {inserted}")

print("\n=== VERIFY ===")
for tbl in TABLES:
    try:
        t_cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        t_cnt = t_cur.fetchone()[0]
    except Exception:
        t_cnt = "-"
    try:
        m_cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        m_cnt = m_cur.fetchone()[0]
    except Exception:
        m_cnt = "-"
    match = "OK" if str(t_cnt) == str(m_cnt) else "MISMATCH"
    print(f"  {tbl}: Turso={t_cnt} MySQL={m_cnt} [{match}]")

m_conn.close()
print("\n=== MIGRATION DONE ===")
