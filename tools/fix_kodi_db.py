import sqlite3, os, datetime

db = os.path.join(os.environ["APPDATA"], "Kodi", "userdata", "Database", "Addons33.db")
print("DB:", db)
conn = sqlite3.connect(db)
cur = conn.cursor()

# Stato attuale
cur.execute("SELECT addonID, enabled, disabledReason FROM installed WHERE addonID LIKE '%video%' OR addonID LIKE '%prippi%'")
print("Prima:")
for r in cur.fetchall():
    print(" ", r)

# Rimuovi vecchia voce s4me
cur.execute("DELETE FROM installed WHERE addonID = 'plugin.video.s4me'")
print("Eliminato plugin.video.s4me")

# Inserisci/aggiorna prippistream
cur.execute("SELECT COUNT(*) FROM installed WHERE addonID = 'plugin.video.prippistream'")
if cur.fetchone()[0] == 0:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        "INSERT INTO installed (addonID, enabled, installDate, lastUpdated, lastUsed, origin, disabledReason) VALUES (?, 1, ?, ?, ?, 'repository.prippistream', 0)",
        ('plugin.video.prippistream', now, now, now)
    )
    print("Inserito plugin.video.prippistream (enabled=1)")
else:
    cur.execute("UPDATE installed SET enabled=1, disabledReason=0 WHERE addonID='plugin.video.prippistream'")
    print("Aggiornato plugin.video.prippistream -> enabled=1")

conn.commit()

# Verifica finale
cur.execute("SELECT addonID, enabled, disabledReason FROM installed WHERE addonID LIKE '%video%' OR addonID LIKE '%prippi%'")
print("Dopo:")
for r in cur.fetchall():
    print(" ", r)

conn.close()
print("OK")
