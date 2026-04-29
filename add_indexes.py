# add_indexes.py
import psycopg
from dbinfo import DBUSER, DBPASS

conn = psycopg.connect(
    f"host=dbclass.rhodescs.org dbname=practice user={DBUSER} password={DBPASS}"
)
cur = conn.cursor()

cur.execute("CREATE INDEX IF NOT EXISTS idx_reservation_room_id ON reservation(room_id)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_reservation_status ON reservation(status)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_useraccount_email ON useraccount(email)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_reservation_status_start ON reservation(status, start_datetime)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_room_block_room_id ON room_block(room_id)")

conn.commit()
conn.close()
print("✅ Indexes created successfully!")