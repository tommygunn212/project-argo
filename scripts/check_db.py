import sqlite3

DB = "data/music.db"
con = sqlite3.connect(DB)
cur = con.cursor()

# Whitelist of allowed table names (prevents SQL injection)
ALLOWED_TABLES = {"artists", "albums", "tracks", "track_genres", "meta"}

for table in ALLOWED_TABLES:
    try:
        # Table name validated against whitelist above
        cur.execute(f"select count(*) from {table}")
        print(table, cur.fetchone()[0])
    except Exception as e:
        print(table, "MISSING", e)

con.close()
