import psycopg
from dbinfo import *

conn = psycopg.connect(
    f"host=dbclass.rhodescs.org dbname=practice user={DBUSER} password={DBPASS}"
)
cur = conn.cursor()

cur.execute("DELETE FROM approval")
cur.execute("DELETE FROM reservation")
cur.execute("DELETE FROM room_block")
cur.execute("DELETE FROM useraccount")
cur.execute("DELETE FROM role")

cur.execute("INSERT INTO role (role_id, role_name) VALUES (1, 'student'), (2, 'admin')")
cur.execute("ALTER TABLE useraccount ADD COLUMN IF NOT EXISTS password_hash VARCHAR(64)")

conn.commit()
conn.close()
print("Done! Database reset successfully.")