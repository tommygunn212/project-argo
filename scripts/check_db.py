import sqlite3

DB = "data/music.db"
con = sqlite3.connect(DB)
cur = con.cursor()

for table in ["artists", "albums", "tracks", "track_genres", "meta"]:
    try:
        cur.execute(f"select count(*) from {table}")
        print(table, cur.fetchone()[0])
    except Exception as e:
        print(table, "MISSING", e)

con.close()
