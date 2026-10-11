import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.expanduser("~/slotex-bot/.env"))

url = os.getenv("TURSO_DATABASE_URL")
token = os.getenv("TURSO_AUTH_TOKEN")

print("URL:", url)
print("Token found:", bool(token))

import turso_serverless
conn = turso_serverless.connect(url, auth_token=token)
cur = conn.cursor()

cur.execute("PRAGMA table_info(orders)")
cols = [r[1] for r in cur.fetchall()]
print("Current columns:", cols)

if "acc_pass" in cols:
    print("acc_pass already exists - kuch karne ki zarurat nahi")
else:
    print("acc_pass MISSING - adding...")
    cur.execute("ALTER TABLE orders ADD COLUMN acc_pass TEXT DEFAULT ''")
    conn.commit()
    print("acc_pass column added")

cur.execute("PRAGMA table_info(orders)")
print("After migration:")
for r in cur.fetchall():
    print(" ", r[1], r[2])
