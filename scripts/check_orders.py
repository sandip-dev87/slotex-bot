import os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.expanduser("~/slotex-bot/.env"))
import turso_serverless

conn = turso_serverless.connect(os.getenv("TURSO_DATABASE_URL"),
                                 auth_token=os.getenv("TURSO_AUTH_TOKEN"))
cur = conn.cursor()

print("=== Last 10 orders ===")
cur.execute("SELECT id, order_no, user_id, game_uid, game_mobile, acc_pass, status, created_at FROM orders ORDER BY id DESC LIMIT 10")
for r in cur.fetchall():
    print(f"id={r[0]} | {r[1]} | uid={r[2]} | g_uid={r[3]} | g_mob={r[4]} | acc_pass={r[5]!r} | {r[6]} | {r[7]}")

print()
print("=== Count total orders ===")
cur.execute("SELECT COUNT(*) FROM orders")
print("Total:", cur.fetchone()[0])

print()
print("=== Orders with empty acc_pass ===")
cur.execute("SELECT COUNT(*) FROM orders WHERE acc_pass IS NULL OR acc_pass = ''")
print("Empty acc_pass:", cur.fetchone()[0])
