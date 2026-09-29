import os
from dotenv import load_dotenv
import turso_serverless
load_dotenv()
c = turso_serverless.connect(os.getenv('TURSO_DATABASE_URL'), auth_token=os.getenv('TURSO_AUTH_TOKEN'))
c.execute("INSERT OR IGNORE INTO admins(phone, password, role) VALUES ('9999999999', 'admin123', 'super')")
c.commit()
r = c.execute("SELECT id, phone, role FROM admins").fetchall()
print("Admins in DB:")
for row in r:
    print(" ", row)
c.close()
