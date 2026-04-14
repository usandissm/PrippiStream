import sqlite3, os

db = os.path.join(os.environ["APPDATA"], "Kodi", "userdata", "Database", "Addons33.db")
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT addonID, enabled, disabledReason FROM installed WHERE addonID LIKE '%video%'")
for r in cur.fetchall():
    print(r)
conn.close()
