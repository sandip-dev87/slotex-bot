CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id TEXT NOT NULL,
    name TEXT NOT NULL,
    mobile TEXT NOT NULL,
    password TEXT NOT NULL,
    account_no TEXT UNIQUE NOT NULL,
    balance REAL DEFAULT 0,
    referral_by TEXT,
    membership_id INTEGER,
    membership_expiry TEXT,
    is_banned INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_tg ON users(tg_id);
CREATE INDEX IF NOT EXISTS idx_users_mobile ON users(mobile);
CREATE INDEX IF NOT EXISTS idx_users_account ON users(account_no);

CREATE TABLE IF NOT EXISTS memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL DEFAULT 0,
    duration_days INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS user_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    membership_id INTEGER NOT NULL,
    starts_at TEXT,
    expires_at TEXT,
    status TEXT DEFAULT 'pending',
    utr TEXT,
    reject_reason TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    url TEXT,
    game_uid TEXT,
    game_mobile TEXT DEFAULT '',
    deposit REAL DEFAULT 0,
    withdrawal REAL DEFAULT 0,
    proof_deposit TEXT,
    proof_withdrawal TEXT,
    proof_stat TEXT,
    status TEXT DEFAULT 'pending',
    reward REAL DEFAULT 0,
    reject_reason TEXT,
    deposit_structure TEXT DEFAULT '',
    instamatch_deposit REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    method TEXT NOT NULL,
    amount REAL NOT NULL,
    fee REAL DEFAULT 0,
    details TEXT,
    status TEXT DEFAULT 'pending',
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_wd_user ON withdrawals(user_id);
CREATE INDEX IF NOT EXISTS idx_wd_status ON withdrawals(status);

CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referrer_id INTEGER NOT NULL,
    referred_id INTEGER NOT NULL,
    order_id INTEGER,
    commission REAL DEFAULT 0,
    status TEXT DEFAULT 'pending',
    credited_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT DEFAULT 'normal'
);

CREATE TABLE IF NOT EXISTS otp_codes (
    mobile TEXT PRIMARY KEY,
    otp TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

INSERT OR IGNORE INTO settings(key,value) VALUES
 ('fee_crypto','5'),
 ('fee_upi','3'),
 ('fee_bank','4'),
 ('min_withdrawal','100'),
 ('min_deposit','50'),
 ('referral_commission','20'),
 ('referral_enabled','1'),
 ('qr_code_file_id',''),
 ('referral_banner_file_id',''),
 ('referral_banner_text','');
