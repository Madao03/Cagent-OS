import sqlite3
db = sqlite3.connect('data/edgar_release.db')
db.execute("DELETE FROM edgar_release_cache WHERE ticker='XPEV' AND quarter_end='2025-12-31'")
db.commit()
c = db.execute("SELECT COUNT(*) FROM edgar_release_cache WHERE ticker='XPEV'").fetchone()[0]
print(f"Cleared Q4 2025. Remaining XPEV entries: {c}")
db.close()
