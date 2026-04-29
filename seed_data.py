"""
seed_data.py
────────────
Branch: feature/seed-data

Populates the database with enough data to satisfy the project requirement:
  total attributes × total tuples ≥ 5000

Breakdown:
  useraccount   (5 cols) ×  200 rows  =  1000
  reservation   (8 cols) ×  400 rows  =  3200
  approval      (5 cols) ×  150 rows  =   750
  room_block    (5 cols) ×   20 rows  =   100
  room          (4 cols) ×   10 rows  =    40
  building      (2 cols) ×    3 rows  =     6
  feature       (2 cols) ×    8 rows  =    16
  room_feature  (2 cols) ×   15 rows  =    30
  role          (2 cols) ×    2 rows  =     4
  ─────────────────────────────────────────────
  TOTAL                               =  5,146

Run once:
  python seed_data.py
"""

import hashlib
import random
from datetime import datetime, timedelta
import psycopg
from psycopg.rows import dict_row
from dbinfo import DBUSER, DBPASS

# ── Connect ────────────────────────────────────────────────────────────────────
conn = psycopg.connect(
    f"host=dbclass.rhodescs.org dbname=practice user={DBUSER} password={DBPASS}"
)
cur = conn.cursor(row_factory=dict_row)


def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()


# ── Clear all tables in correct foreign key order ─────────────────────────────
print("Clearing existing data...")
cur.execute("DELETE FROM approval")
cur.execute("DELETE FROM reservation")
cur.execute("DELETE FROM room_block")
cur.execute("DELETE FROM room_feature")
cur.execute("DELETE FROM room")
cur.execute("DELETE FROM feature")
cur.execute("DELETE FROM building")
cur.execute("DELETE FROM useraccount")
cur.execute("DELETE FROM role")
conn.commit()

# ── 1. Roles ───────────────────────────────────────────────────────────────────
print("Seeding roles...")
cur.execute("""
    INSERT INTO role (role_id, role_name) VALUES
        (1, 'student'),
        (2, 'admin')
""")

# ── 2. Buildings ───────────────────────────────────────────────────────────────
print("Seeding buildings...")
cur.execute("""
    INSERT INTO building (building_id, building_name) VALUES
        (1, 'Paul Barrett, Jr. Library'),
        (2, 'Barret Hall'),
        (3, 'Kennedy Hall')
""")

# ── 3. Features ────────────────────────────────────────────────────────────────
print("Seeding features...")
cur.execute("""
    INSERT INTO feature (feature_id, feature_name) VALUES
        (1, 'Whiteboard'),
        (2, 'Projector'),
        (3, 'Video Conferencing'),
        (4, 'Standing Desks'),
        (5, 'Natural Light'),
        (6, 'Sound Proof'),
        (7, 'TV Screen'),
        (8, 'Printer Access')
""")

# ── 4. Rooms ───────────────────────────────────────────────────────────────────
print("Seeding rooms...")
rooms = [
    (1,  'Study Room A',      4,  1),
    (2,  'Study Room B',      8,  1),
    (3,  'Quiet Room',        2,  1),
    (4,  'Group Room 1',      10, 1),
    (5,  'Conference Room',   12, 1),
    (6,  'Media Lab',         6,  1),
    (7,  'Seminar Room A',    20, 2),
    (8,  'Seminar Room B',    20, 2),
    (9,  'Innovation Hub',    15, 3),
    (10, 'Collaboration Pod', 6,  3),
]
for room_id, name, capacity, building_id in rooms:
    cur.execute("""
        INSERT INTO room (room_id, room_name, capacity, building_id)
        VALUES (%s, %s, %s, %s)
    """, [room_id, name, capacity, building_id])

# ── 5. Room features (15 pairings) ────────────────────────────────────────────
print("Seeding room features...")
room_features = [
    (1, 1), (1, 5),
    (2, 1), (2, 2),
    (3, 1), (3, 6),
    (4, 2), (4, 3),
    (5, 2), (5, 3), (5, 7),
    (6, 7), (6, 8),
    (7, 4),
    (10, 5),
]
for room_id, feature_id in room_features:
    cur.execute("""
        INSERT INTO room_feature (room_id, feature_id) VALUES (%s, %s)
    """, [room_id, feature_id])

# ── 6. Users (200 total) ───────────────────────────────────────────────────────
print("Seeding users...")
first_names = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael",
    "Linda", "William", "Barbara", "David", "Susan", "Richard", "Jessica",
    "Joseph", "Sarah", "Thomas", "Karen", "Charles", "Lisa", "Emily",
    "Daniel", "Ashley", "Matthew", "Sophia", "Anthony", "Isabella", "Mark",
    "Olivia", "Donald", "Ava", "Steven", "Mia", "Paul", "Charlotte",
    "Andrew", "Amelia", "Joshua", "Harper", "Kenneth", "Evelyn", "Kevin",
    "Abigail", "Brian", "Ella", "George", "Scarlett", "Timothy", "Grace", "Ronald"
]
last_names = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
    "Carter", "Roberts"
]
domains = ["rhodes.edu", "memphis.edu", "vanderbilt.edu", "tulane.edu", "sewanee.edu"]

user_ids = []
for i in range(1, 201):
    first   = random.choice(first_names)
    last    = random.choice(last_names)
    name    = f"{first} {last}"
    email   = f"{first.lower()}.{last.lower()}{i}@{random.choice(domains)}"
    role_id = 2 if i <= 5 else 1

    cur.execute("""
        INSERT INTO useraccount (user_id, name, email, role_id, password_hash)
        VALUES (%s, %s, %s, %s, %s)
    """, [i, name, email, role_id, hash_password("password123")])
    user_ids.append(i)

conn.commit()

# ── 7. Reservations (400) ──────────────────────────────────────────────────────
print("Seeding reservations...")
purposes = [
    'Group Study', 'Project Meeting', 'Tutoring Session',
    'Club Meeting', 'Research Session', 'Study Group',
    'Interview Prep', 'General Use'
]
statuses_weighted = (
    ['approved'] * 50 +
    ['pending']  * 30 +
    ['rejected'] * 20
)

base_date = datetime.now() - timedelta(days=90)
room_ids  = [r[0] for r in rooms]
reservations_inserted = []

for reservation_id in range(1, 401):
    user_id        = random.choice(user_ids[5:])
    room_id        = random.choice(room_ids)
    status         = random.choice(statuses_weighted)
    offset_days    = random.randint(0, 119)
    offset_hours   = random.choice(range(8, 20))
    offset_minutes = random.choice([0, 30])
    start_dt       = (base_date + timedelta(days=offset_days)).replace(
                         hour=offset_hours, minute=offset_minutes,
                         second=0, microsecond=0)
    duration_mins  = random.choice([30, 60, 90, 120, 150, 180, 210, 240])
    end_dt         = start_dt + timedelta(minutes=duration_mins)
    purpose        = random.choice(purposes)
    attendee_count = random.randint(1, 8)

    cur.execute("""
        INSERT INTO reservation
            (reservation_id, user_id, room_id, start_datetime, end_datetime,
             purpose, attendee_count, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, [reservation_id, user_id, room_id, start_dt, end_dt,
          purpose, attendee_count, status])
    reservations_inserted.append((reservation_id, status))

conn.commit()

# ── 8. Approvals (150) ────────────────────────────────────────────────────────
print("Seeding approvals...")
admin_ids = list(range(1, 6))
decided   = [(rid, st) for rid, st in reservations_inserted if st in ('approved', 'rejected')]
random.shuffle(decided)
decided   = decided[:150]

for approval_id, (res_id, decision) in enumerate(decided, start=1):
    admin_id      = random.choice(admin_ids)
    decision_time = datetime.now() - timedelta(days=random.randint(0, 89))
    cur.execute("""
        INSERT INTO approval (approval_id, reservation_id, admin_id, decision, decision_time)
        VALUES (%s, %s, %s, %s, %s)
    """, [approval_id, res_id, admin_id, decision, decision_time])

conn.commit()

# ── 9. Room blocks (20) ───────────────────────────────────────────────────────
print("Seeding room blocks...")
block_reasons = [
    'Maintenance', 'Deep Cleaning', 'Private Event',
    'IT Upgrade', 'Reserved for Exam'
]

for block_id in range(1, 21):
    room_id  = random.choice(room_ids)
    start_dt = (datetime.now() + timedelta(days=random.randint(1, 60))).replace(
                   hour=random.choice([8, 9, 10, 14]), minute=0, second=0, microsecond=0)
    end_dt   = start_dt + timedelta(hours=random.choice([2, 4, 8]))
    reason   = random.choice(block_reasons)

    cur.execute("""
        INSERT INTO room_block (block_id, room_id, start_datetime, end_datetime, reason)
        VALUES (%s, %s, %s, %s, %s)
    """, [block_id, room_id, start_dt, end_dt, reason])

# ── Final commit ──────────────────────────────────────────────────────────────
conn.commit()
conn.close()

print("\n✅ Seed complete!")
print("   200 users  (IDs 1–5 are admins, 6–200 are students)")
print("   400 reservations")
print("   150 approvals")
print("    20 room blocks")
print("    10 rooms across 3 buildings")
print("\n   All seeded users have password: password123")
print("   To find an admin email, check user IDs 1–5 in your useraccount table")
print("\n   Estimated total attribute × tuple count: 5,146")