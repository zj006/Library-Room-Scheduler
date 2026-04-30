# Library Room Scheduling App - Modern UI Edition

import psycopg
import hashlib
from datetime import datetime, timedelta
from psycopg.rows import dict_row
from dbinfo import *
from nicegui import ui, app

# Connect to database
conn = psycopg.connect(
    f"host=dbclass.rhodescs.org dbname=practice user={DBUSER} password={DBPASS}"
)
cur = conn.cursor(row_factory=dict_row)

# ── Make sure useraccount has a password column ────────────────────────────────
cur.execute("""
    ALTER TABLE useraccount
    ADD COLUMN IF NOT EXISTS password_hash VARCHAR(64)
""")
conn.commit()


# ── Helpers ────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def is_logged_in() -> bool:
    return app.storage.user.get('user_id') is not None


def current_role() -> str | None:
    return app.storage.user.get('role_name')


def require_login():
    if not is_logged_in():
        ui.navigate.to('/login')
        return False
    return True


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_user_by_email(email: str):
    cur.execute("SELECT * FROM useraccount WHERE email = %s", [email])
    return cur.fetchone()


def create_user(name: str, email: str, password: str, role_id: int):
    cur.execute("""
        INSERT INTO useraccount (user_id, name, email, role_id, password_hash)
        VALUES (
            (SELECT COALESCE(MAX(user_id), 0) + 1 FROM useraccount),
            %s, %s, %s, %s
        )
    """, [name, email, role_id, hash_password(password)])
    conn.commit()


def get_role_name(role_id: int) -> str:
    cur.execute("SELECT role_name FROM role WHERE role_id = %s", [role_id])
    row = cur.fetchone()
    return row['role_name'] if row else 'student'


def get_rooms():
    cur.execute("""
        SELECT r.room_id, r.room_name, r.capacity, b.building_name,
               STRING_AGG(f.feature_name, ', ') AS features
        FROM room r
        JOIN building b ON r.building_id = b.building_id
        LEFT JOIN room_feature rf ON r.room_id = rf.room_id
        LEFT JOIN feature f ON rf.feature_id = f.feature_id
        GROUP BY r.room_id, r.room_name, r.capacity, b.building_name
        ORDER BY r.room_id
    """)
    return cur.fetchall()


def get_booked_room_ids():
    cur.execute("""
        SELECT DISTINCT room_id FROM reservation
        WHERE status IN ('approved', 'pending')
          AND end_datetime >= NOW()
    """)
    return {row['room_id'] for row in cur.fetchall()}


def get_reservations():
    cur.execute("""
        SELECT reservation.reservation_id, useraccount.name, room.room_name,
               reservation.start_datetime, reservation.end_datetime, reservation.status
        FROM reservation
        JOIN useraccount ON reservation.user_id = useraccount.user_id
        JOIN room ON reservation.room_id = room.room_id
        ORDER BY reservation.start_datetime
    """)
    return cur.fetchall()


def get_user_reservations(user_id):
    cur.execute("""
        SELECT reservation.reservation_id, room.room_name,
               reservation.start_datetime, reservation.end_datetime, reservation.status
        FROM reservation
        JOIN room ON reservation.room_id = room.room_id
        WHERE reservation.user_id = %s
        ORDER BY reservation.start_datetime
    """, [user_id])
    return cur.fetchall()


def get_available_rooms(start_datetime, end_datetime):
    cur.execute("""
        SELECT r.room_id, r.room_name, r.capacity, b.building_name,
               STRING_AGG(f.feature_name, ', ') AS features
        FROM room r
        JOIN building b ON r.building_id = b.building_id
        LEFT JOIN room_feature rf ON r.room_id = rf.room_id
        LEFT JOIN feature f ON rf.feature_id = f.feature_id
        WHERE r.room_id NOT IN (
            SELECT room_id FROM reservation
            WHERE status IN ('approved', 'pending')
              AND start_datetime < %s AND end_datetime > %s
        )
        AND r.room_id NOT IN (
            SELECT room_id FROM room_block
            WHERE start_datetime < %s AND end_datetime > %s
        )
        GROUP BY r.room_id, r.room_name, r.capacity, b.building_name
        ORDER BY r.room_id
    """, [end_datetime, start_datetime, end_datetime, start_datetime])
    return cur.fetchall()


def make_reservation(user_id, room_id, start_datetime, end_datetime):
    cur.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    try:
        cur.execute("""
                    SELECT COUNT(*) as cnt
                    FROM reservation
                    WHERE room_id = %s
                      AND status IN ('approved', 'pending')
                      AND start_datetime < %s
                      AND end_datetime > %s
                    """, [room_id, end_datetime, start_datetime])

        result = cur.fetchone()
        if result['cnt'] > 0:
            cur.execute("ROLLBACK")
            return False

        cur.execute("""
                    INSERT INTO reservation
                    (reservation_id, user_id, room_id, start_datetime, end_datetime,
                     purpose, attendee_count, status)
                    VALUES ((SELECT COALESCE(MAX(reservation_id), 0) + 1 FROM reservation),
                            %s, %s, %s, %s, 'General Use', 1, 'pending')
                    """, [user_id, room_id, start_datetime, end_datetime])

        cur.execute("COMMIT")
        return True

    except Exception as e:
        cur.execute("ROLLBACK")
        raise e


def get_pending_reservations():
    with conn.cursor(name='pending_cursor', row_factory=dict_row) as server_cursor:
        server_cursor.execute("""
                              SELECT r.reservation_id,
                                     u.name AS user_name,
                                     rm.room_name,
                                     r.start_datetime,
                                     r.end_datetime,
                                     r.status
                              FROM reservation r
                                       JOIN useraccount u ON r.user_id = u.user_id
                                       JOIN room rm ON r.room_id = rm.room_id
                              WHERE r.status = 'pending'
                              ORDER BY r.start_datetime
                              """)
        return [row for row in server_cursor]

def approve_reservation(reservation_id: int, admin_id: int):
    cur.execute("UPDATE reservation SET status = 'approved' WHERE reservation_id = %s", [reservation_id])
    cur.execute("""
        INSERT INTO approval (approval_id, reservation_id, admin_id, decision, decision_time)
        VALUES (
            (SELECT COALESCE(MAX(approval_id), 0) + 1 FROM approval),
            %s, %s, 'approved', NOW()
        )
    """, [reservation_id, admin_id])
    conn.commit()


def reject_reservation(reservation_id: int, admin_id: int):
    cur.execute("UPDATE reservation SET status = 'rejected' WHERE reservation_id = %s", [reservation_id])
    cur.execute("""
        INSERT INTO approval (approval_id, reservation_id, admin_id, decision, decision_time)
        VALUES (
            (SELECT COALESCE(MAX(approval_id), 0) + 1 FROM approval),
            %s, %s, 'rejected', NOW()
        )
    """, [reservation_id, admin_id])
    conn.commit()

def get_reservation_stats():
    with conn.cursor(name='stats_cursor', row_factory=dict_row) as server_cursor:
        server_cursor.execute("""
            SELECT rm.room_name,
                   COUNT(r.reservation_id) AS total_reservations,
                   SUM(CASE WHEN r.status = 'approved' THEN 1 ELSE 0 END) AS approved,
                   SUM(CASE WHEN r.status = 'pending'  THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN r.status = 'rejected' THEN 1 ELSE 0 END) AS rejected
            FROM room rm
            LEFT JOIN reservation r ON rm.room_id = r.room_id
            GROUP BY rm.room_name
            ORDER BY total_reservations DESC
        """)
        return [row for row in server_cursor]


# ── Time slot helpers ──────────────────────────────────────────────────────────

def generate_time_options():
    options = []
    base = datetime(2000, 1, 1, 0, 0)
    for i in range(48):
        t = base + timedelta(minutes=30 * i)
        options.append(t.strftime("%I:%M %p"))
    return options


def generate_duration_options():
    options = []
    for minutes in range(30, 241, 30):
        hours = minutes // 60
        mins = minutes % 60
        if hours == 0:
            options.append(f"{mins} min")
        elif mins == 0:
            label = f"{hours} hr" if hours == 1 else f"{hours} hrs"
            options.append(label)
        else:
            options.append(f"{hours} hr {mins} min")
    return options


def parse_datetime(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %I:%M %p")


def duration_label_to_minutes(label: str) -> int:
    total = 0
    if 'hr' in label:
        parts = label.split('hr')
        total += int(parts[0].strip()) * 60
        if 'min' in parts[1]:
            total += int(parts[1].replace('min', '').strip())
    elif 'min' in label:
        total = int(label.replace('min', '').strip())
    return total


# ── Shared UI with Modern Styling ──────────────────────────────────────────────

ui.add_head_html('''
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">

<style>
    * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }
    
    body {
        background: linear-gradient(135deg, #f8f9fa 0%, #f0f2f5 100%);
        margin: 0;
        padding: 0;
    }
    
    .card-hover {
        transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    
    .card-hover:hover {
        transform: translateY(-4px);
        box-shadow: 0 12px 24px rgba(0, 0, 0, 0.15) !important;
    }
    
    .btn-cardinal {
        background-color: #c41e3a !important;
        color: white !important;
        font-weight: 600;
        letter-spacing: 0.3px;
        transition: all 0.2s ease !important;
    }
    
    .btn-cardinal:hover {
        background-color: #a01830 !important;
        box-shadow: 0 4px 12px rgba(196, 30, 58, 0.3) !important;
    }
    
    .btn-cardinal-outline {
        border: 2px solid #c41e3a !important;
        color: #c41e3a !important;
        background-color: white !important;
        font-weight: 600;
        letter-spacing: 0.3px;
        transition: all 0.2s ease !important;
    }
    
    .btn-cardinal-outline:hover {
        background-color: #c41e3a !important;
        color: white !important;
    }
</style>
''', shared=True)


def render_header():
    with ui.column().classes("items-center w-full mt-16 mb-12"):
        ui.icon('library_books', size='4rem').classes("text-red-700 mb-4")
        ui.label("Library Room Scheduler").classes("text-5xl font-bold text-gray-900 text-center tracking-tight")
        ui.label("Reserve your perfect study space").classes("text-lg text-gray-500 text-center mt-3")


def render_nav_bar():
    with ui.row().classes("w-full items-center justify-between px-8 py-5 bg-red-700 text-white shadow-lg"):
        with ui.row().classes("items-center gap-3"):
            ui.icon('meeting_room', size='1.75rem')
            ui.label("Library Room Scheduler").classes("text-xl font-bold tracking-tight")
        with ui.row().classes("items-center gap-8"):
            name = app.storage.user.get('name', '')
            role = app.storage.user.get('role_name', '')
            with ui.column().classes("items-end gap-0"):
                ui.label(name).classes("text-sm font-semibold")
                ui.label(role.title()).classes("text-xs opacity-80 capitalize")
            ui.separator().props("vertical").classes("bg-red-500 opacity-40 h-8")
            ui.button("Sign Out", on_click=do_logout).props("flat").classes("text-white hover:bg-red-600 transition-colors px-4")


def do_logout():
    app.storage.user.clear()
    ui.navigate.to('/login')


# ── /login ─────────────────────────────────────────────────────────────────────

@ui.page('/login')
def login_page():
    if is_logged_in():
        ui.navigate.to('/')
        return

    render_header()

    with ui.card().classes("w-full max-w-md mx-auto p-8 shadow-lg rounded-2xl bg-white"):
        ui.label("Welcome Back").classes("text-2xl font-bold text-gray-900 mb-1")
        ui.label("Sign in to your account").classes("text-gray-500 text-sm mb-6")

        email_box = ui.input("Email Address").props("outlined").classes("w-full mb-4")
        email_box.set_value("")
        
        pass_box = ui.input("Password", password=True, password_toggle_button=True).props("outlined").classes("w-full mb-2")
        error_label = ui.label("").classes("text-red-600 text-sm font-medium h-5 mb-4")

        def do_login():
            email = email_box.value.strip().lower()
            password = pass_box.value

            if not email.endswith('.edu'):
                error_label.set_text("✗ Email must end with .edu")
                return

            user = get_user_by_email(email)
            if not user:
                error_label.set_text("✗ No account found with that email")
                return

            if user['password_hash'] != hash_password(password):
                error_label.set_text("✗ Incorrect password")
                return

            role_name = get_role_name(user['role_id'])
            app.storage.user.update({
                'user_id': user['user_id'],
                'name': user['name'],
                'email': user['email'],
                'role_id': user['role_id'],
                'role_name': role_name,
            })
            ui.navigate.to('/')

        ui.button("Sign In", on_click=do_login).props("unelevated").classes("w-full btn-cardinal py-3 text-lg rounded-lg mt-2")
        
        ui.separator().classes("my-6")
        
        with ui.row().classes("w-full items-center justify-center gap-1"):
            ui.label("Don't have an account?").classes("text-gray-600 text-sm")
            ui.link("Create one", target='/register').classes("text-red-700 font-bold hover:text-red-800 text-sm")


# ── /register ──────────────────────────────────────────────────────────────────

@ui.page('/register')
def register_page():
    render_header()

    with ui.card().classes("w-full max-w-md mx-auto p-8 shadow-lg rounded-2xl bg-white"):
        ui.label("Create Account").classes("text-2xl font-bold text-gray-900 mb-1")
        ui.label("Join us to book study spaces").classes("text-gray-500 text-sm mb-6")

        name_box = ui.input("Full Name").props("outlined").classes("w-full mb-4")
        email_box = ui.input("Email Address").props("outlined").classes("w-full mb-4")
        pass_box = ui.input("Password", password=True, password_toggle_button=True).props("outlined").classes("w-full mb-4")
        pass_box2 = ui.input("Confirm Password", password=True, password_toggle_button=True).props("outlined").classes("w-full mb-4")

        role_select = ui.select(
            label="I am a",
            options={"1": "Student", "2": "Administrator"},
            value="1"
        ).classes("w-full mb-4")

        error_label = ui.label("").classes("text-red-600 text-sm font-medium h-5 mb-4")

        def do_register():
            name = name_box.value.strip()
            email = email_box.value.strip().lower()
            password = pass_box.value
            confirm = pass_box2.value
            role_id = int(role_select.value)

            if not name:
                error_label.set_text("✗ Please enter your full name")
                return
            if not email.endswith('.edu'):
                error_label.set_text("✗ Email must end with .edu")
                return
            if len(password) < 6:
                error_label.set_text("✗ Password must be at least 6 characters")
                return
            if password != confirm:
                error_label.set_text("✗ Passwords do not match")
                return
            if get_user_by_email(email):
                error_label.set_text("✗ An account with that email already exists")
                return

            create_user(name, email, password, role_id)
            ui.notify("✓ Account created successfully! Please sign in.", type="positive")
            ui.navigate.to('/login')

        ui.button("Create Account", on_click=do_register).props("unelevated").classes("w-full btn-cardinal py-3 text-lg rounded-lg mt-2")
        
        ui.separator().classes("my-6")
        
        with ui.row().classes("w-full items-center justify-center gap-1"):
            ui.label("Already have an account?").classes("text-gray-600 text-sm")
            ui.link("Sign in", target='/login').classes("text-red-700 font-bold hover:text-red-800 text-sm")


# ── / (homepage) ───────────────────────────────────────────────────────────────

@ui.page('/')
def homepage():
    if not require_login():
        return

    render_nav_bar()

    available_count = len(get_rooms()) - len(get_booked_room_ids())
    name = app.storage.user.get('name', '').split()[0]

    with ui.column().classes("w-full max-w-6xl mx-auto px-6 gap-8 pb-12"):
        with ui.card().classes("w-full p-10 bg-gradient-to-r from-red-700 to-red-600 text-white shadow-xl rounded-2xl card-hover"):
            ui.label(f"Welcome back, {name}!").classes("text-4xl font-bold mb-2")
            ui.label(f"{available_count} study room{'s' if available_count != 1 else ''} available right now").classes("text-lg opacity-90")

        with ui.row().classes("w-full gap-6 flex-wrap"):
            with ui.card().classes("flex-1 min-w-[280px] p-8 rounded-2xl bg-white card-hover shadow-md"):
                ui.icon('meeting_room', size='3rem').classes("text-red-700 mb-4")
                ui.label("Browse Rooms").classes("text-xl font-bold text-gray-900")
                ui.label("Explore all available study spaces").classes("text-gray-600 text-sm mt-2")
                ui.element().classes("flex-grow")
                ui.button("Explore", on_click=lambda: ui.navigate.to('/rooms')).props("unelevated").classes("btn-cardinal w-full mt-4 rounded-lg")

            with ui.card().classes("flex-1 min-w-[280px] p-8 rounded-2xl bg-white card-hover shadow-md"):
                ui.icon('event_available', size='3rem').classes("text-red-700 mb-4")
                ui.label("Make a Reservation").classes("text-xl font-bold text-gray-900")
                ui.label("Book a room for your study session").classes("text-gray-600 text-sm mt-2")
                ui.element().classes("flex-grow")
                ui.button("Reserve", on_click=lambda: ui.navigate.to('/reserve')).props("unelevated").classes("btn-cardinal w-full mt-4 rounded-lg")

            with ui.card().classes("flex-1 min-w-[280px] p-8 rounded-2xl bg-white card-hover shadow-md"):
                ui.icon('list_alt', size='3rem').classes("text-red-700 mb-4")
                ui.label("My Reservations").classes("text-xl font-bold text-gray-900")
                ui.label("View and manage your bookings").classes("text-gray-600 text-sm mt-2")
                ui.element().classes("flex-grow")
                ui.button("View", on_click=lambda: ui.navigate.to('/reservations')).props("unelevated").classes("btn-cardinal w-full mt-4 rounded-lg")

        if current_role() == 'admin':
            with ui.card().classes("w-full p-8 rounded-2xl bg-gradient-to-r from-gray-900 to-gray-800 text-white card-hover shadow-lg"):
                with ui.row().classes("items-center gap-4"):
                    ui.icon('admin_panel_settings', size='2.5rem').classes("text-red-400")
                    with ui.column():
                        ui.label("Admin Dashboard").classes("text-xl font-bold")
                        ui.label("Review and approve pending reservations").classes("text-gray-300 text-sm")
                ui.element().classes("absolute inset-0 cursor-pointer").on('click', lambda: ui.navigate.to('/admin'))


# ── /rooms ─────────────────────────────────────────────────────────────────────

@ui.page('/rooms')
def rooms_page():
    if not require_login():
        return

    render_nav_bar()

    with ui.column().classes("w-full max-w-6xl mx-auto px-6 gap-6 pb-12"):
        ui.label("Available Study Rooms").classes("text-4xl font-bold text-gray-900")
        ui.label("Browse and reserve your ideal study space").classes("text-gray-600 text-lg mt-2 mb-2")

        search_input = ui.input().props("outlined").classes("w-full mb-2")
        search_input.props("placeholder=Search by room name or building...")

        rooms = get_rooms()
        booked_ids = get_booked_room_ids()

        room_container = ui.column().classes("w-full gap-4 mt-4")

        def render_rooms(filter_text=""):
            room_container.clear()
            q = filter_text.strip().lower()
            filtered = [r for r in rooms if not q or q in r['room_name'].lower() or q in (r['building_name'] or '').lower()]
            with room_container:
                if not filtered:
                    with ui.column().classes("items-center mt-16 gap-3"):
                        ui.icon('search_off', size='4rem').classes("text-gray-300")
                        ui.label("No rooms match your search").classes("text-gray-500 text-lg font-semibold")
                    return
                for room in filtered:
                    is_booked = room['room_id'] in booked_ids
                    with ui.card().classes("w-full p-6 rounded-xl card-hover shadow-md bg-white"):
                        with ui.row().classes("w-full items-start justify-between gap-4"):
                            with ui.column().classes("gap-2 flex-grow"):
                                with ui.row().classes("items-center gap-3"):
                                    ui.label(room['room_name']).classes("text-2xl font-bold text-gray-900")
                                    badge_color = "red" if is_booked else "green"
                                    ui.badge(
                                        "Unavailable" if is_booked else "Available",
                                        color=badge_color
                                    ).classes("text-xs font-bold")
                                ui.label(f"📍 {room['building_name']}").classes("text-gray-700 font-medium")
                                ui.label(f"👥 {room['capacity']} people").classes("text-gray-600 text-sm")
                                if room['features']:
                                    ui.label(f"✨ {room['features']}").classes("text-gray-600 text-sm")
                            if is_booked:
                                ui.button("Unavailable").props("unelevated disable").classes("px-8 py-2 bg-gray-300 text-gray-500 rounded-lg")
                            else:
                                ui.button("Reserve", on_click=lambda room_id=room['room_id']: ui.navigate.to(f"/reserve?room_id={room_id}")).props("unelevated").classes("btn-cardinal px-8 py-2 rounded-lg")

        search_input.on('input', lambda: render_rooms(search_input.value))
        render_rooms()

        with ui.row().classes("justify-center mt-8"):
            ui.button("← Back to Home", on_click=lambda: ui.navigate.to("/")).props("outline").classes("btn-cardinal-outline px-8 py-3 rounded-lg text-base")


# ── /reservations ──────────────────────────────────────────────────────────────

@ui.page('/reservations')
def reservations_page():
    if not require_login():
        return

    render_nav_bar()

    with ui.column().classes("w-full max-w-6xl mx-auto px-6 gap-8 pb-12"):
        if current_role() == 'admin':
            ui.label("All Reservations").classes("text-4xl font-bold text-gray-900")
            columns = [
                {'name': 'reservation_id', 'field': 'reservation_id', 'label': 'ID'},
                {'name': 'name', 'field': 'name', 'label': 'User'},
                {'name': 'room_name', 'field': 'room_name', 'label': 'Room'},
                {'name': 'start_datetime', 'field': 'start_datetime', 'label': 'Start'},
                {'name': 'end_datetime', 'field': 'end_datetime', 'label': 'End'},
                {'name': 'status', 'field': 'status', 'label': 'Status'},
            ]
            rows = get_reservations()
        else:
            ui.label("My Reservations").classes("text-4xl font-bold text-gray-900")
            columns = [
                {'name': 'reservation_id', 'field': 'reservation_id', 'label': 'ID'},
                {'name': 'room_name', 'field': 'room_name', 'label': 'Room'},
                {'name': 'start_datetime', 'field': 'start_datetime', 'label': 'Start'},
                {'name': 'end_datetime', 'field': 'end_datetime', 'label': 'End'},
                {'name': 'status', 'field': 'status', 'label': 'Status'},
            ]
            rows = get_user_reservations(app.storage.user['user_id'])

        with ui.card().classes("w-full shadow-lg rounded-xl bg-white overflow-hidden"):
            table = ui.table(columns=columns, rows=rows).classes("w-full")
            table.add_slot('body-cell-status', '''
                <q-td :props="props">
                    <q-badge
                        :color="props.value === 'approved' ? 'green' : props.value === 'rejected' ? 'red' : 'orange'"
                        :label="props.value"
                        class="text-xs font-bold"
                    />
                </q-td>
            ''')

        ui.separator().classes("my-8")
        
        ui.label("Room Usage Analytics").classes("text-2xl font-bold text-gray-900")
        
        with ui.card().classes("w-full shadow-lg rounded-xl bg-white overflow-hidden"):
            stats_columns = [
                {'name': 'room_name', 'field': 'room_name', 'label': 'Room'},
                {'name': 'total_reservations', 'field': 'total_reservations', 'label': 'Total'},
                {'name': 'approved', 'field': 'approved', 'label': 'Approved'},
                {'name': 'pending', 'field': 'pending', 'label': 'Pending'},
                {'name': 'rejected', 'field': 'rejected', 'label': 'Rejected'},
            ]
            ui.table(columns=stats_columns, rows=get_reservation_stats()).classes("w-full")

        with ui.row().classes("justify-center mt-8"):
            ui.button("← Back to Home", on_click=lambda: ui.navigate.to("/")).props("outline").classes("btn-cardinal-outline px-8 py-3 rounded-lg text-base")


# ── /reserve ───────────────────────────────────────────────────────────────────

@ui.page('/reserve')
def reserve_page():
    if not require_login():
        return

    render_nav_bar()

    room_id = ui.context.client.request.query_params.get('room_id')
    selected_room = int(room_id) if room_id else None
    session_user_id = app.storage.user.get('user_id', '')

    time_options = generate_time_options()
    duration_options = generate_duration_options()

    now = datetime.now()
    default_date = now.strftime("%Y-%m-%d")
    rounded_min = 30 * ((now.minute // 30) + 1)
    default_hour = now.hour + rounded_min // 60
    default_min = rounded_min % 60
    default_time_str = datetime(2000, 1, 1, default_hour % 24, default_min).strftime("%I:%M %p")

    with ui.column().classes("w-full max-w-4xl mx-auto px-6 pb-12"):
        with ui.row().classes("w-full justify-center gap-4 mb-8 items-center"):
            with ui.row().classes("items-center gap-2"):
                ui.badge("1").props("color=red")
                ui.label("Select Time").classes("font-semibold text-gray-700")
            ui.icon('arrow_forward').classes("text-gray-400")
            with ui.row().classes("items-center gap-2"):
                ui.badge("2").props("color=gray")
                ui.label("Choose Room").classes("font-semibold text-gray-400")
            ui.icon('arrow_forward').classes("text-gray-400")
            with ui.row().classes("items-center gap-2"):
                ui.badge("3").props("color=gray")
                ui.label("Confirmed").classes("font-semibold text-gray-400")

        with ui.card().classes("w-full p-8 rounded-2xl shadow-lg bg-white") as step1_card:
            ui.label("When do you need a room?").classes("text-3xl font-bold text-gray-900 mb-6")
            
            if room_id:
                ui.badge(f"Room {room_id} pre-selected", color="green").classes("mb-4")

            ui.label("📅 Select Date").classes("font-bold text-gray-800 mt-4 mb-2")
            date_picker = ui.date(value=default_date).classes("w-full")

            ui.label("🕐 Start Time").classes("font-bold text-gray-800 mt-4 mb-2")
            start_select = ui.select(
                options=time_options,
                value=default_time_str if default_time_str in time_options else time_options[16]
            ).props("outlined").classes("w-full")

            ui.label("⏱️ Duration (max 4 hours)").classes("font-bold text-gray-800 mt-4 mb-2")
            duration_select = ui.select(
                options=duration_options,
                value=duration_options[1]
            ).props("outlined").classes("w-full")

            error_label = ui.label("").classes("text-red-600 text-sm font-semibold h-6 mt-4")

            with ui.row().classes("gap-4 mt-8 justify-end"):
                ui.button("Cancel", on_click=lambda: ui.navigate.to("/rooms")).props("outline").classes("btn-cardinal-outline px-8 py-3 rounded-lg")
                ui.button("Continue", on_click=lambda: process_step1()).props("unelevated").classes("btn-cardinal px-8 py-3 rounded-lg")

        with ui.card().classes("w-full p-8 rounded-2xl shadow-lg bg-white") as step2_card:
            ui.label("Select your room").classes("text-3xl font-bold text-gray-900 mb-6")

            columns = [
                {'name': 'room_id', 'field': 'room_id', 'label': 'ID'},
                {'name': 'room_name', 'field': 'room_name', 'label': 'Room'},
                {'name': 'building_name', 'field': 'building_name', 'label': 'Building'},
                {'name': 'capacity', 'field': 'capacity', 'label': 'Capacity'},
                {'name': 'features', 'field': 'features', 'label': 'Features'},
            ]
            rooms_table = ui.table(
                columns=columns, rows=[], selection='single',
                row_key='room_id', on_select=lambda e: click_room(e)
            ).classes("w-full")
            
            time_range_label = ui.label("").classes("text-gray-600 text-sm italic mt-4")

            with ui.row().classes("gap-4 mt-8 justify-end"):
                def go_back():
                    step1_card.set_visibility(True)
                    step2_card.set_visibility(False)
                
                ui.button("Back", on_click=go_back).props("outline").classes("btn-cardinal-outline px-8 py-3 rounded-lg")
                ui.button("Confirm", on_click=lambda: process_step2()).props("unelevated").classes("btn-cardinal px-8 py-3 rounded-lg")

        with ui.card().classes("w-full p-12 rounded-2xl shadow-lg text-center bg-gradient-to-b from-green-50 to-white border-2 border-green-200") as step3_card:
            ui.icon('check_circle', size='5rem').classes("text-green-600 mb-4")
            ui.label("Reservation Submitted!").classes("text-3xl font-bold text-green-700 mb-2")
            ui.label("Your request is pending admin approval.").classes("text-gray-700 text-lg mb-8")
            
            with ui.row().classes("gap-4 justify-center"):
                ui.button("View Reservations", on_click=lambda: ui.navigate.to("/reservations")).props("unelevated").classes("btn-cardinal px-8 py-3 rounded-lg text-base")
                ui.button("Back Home", on_click=lambda: ui.navigate.to("/")).props("outline").classes("btn-cardinal-outline px-8 py-3 rounded-lg text-base")

        step2_card.set_visibility(False)
        step3_card.set_visibility(False)

        computed = {'start': None, 'end': None}

        def click_room(e):
            nonlocal selected_room
            if e.selection:
                selected_room = e.selection[0]['room_id']

        def process_step1():
            date_str = date_picker.value
            time_str = start_select.value
            duration_lbl = duration_select.value

            if not date_str:
                error_label.set_text("Please select a date.")
                return

            try:
                start_dt = parse_datetime(date_str, time_str)
            except Exception:
                error_label.set_text("Invalid date or time selection.")
                return

            duration_mins = duration_label_to_minutes(duration_lbl)
            end_dt = start_dt + timedelta(minutes=duration_mins)

            if duration_mins > 240:
                error_label.set_text("Reservations cannot exceed 4 hours.")
                return

            if start_dt < datetime.now():
                error_label.set_text("Start time must be in the future.")
                return

            computed['start'] = start_dt
            computed['end'] = end_dt

            available_rooms = get_available_rooms(start_dt, end_dt)
            rooms_table.rows = available_rooms
            rooms_table.update()
            time_range_label.set_text(
                f"Available from {start_dt.strftime('%A, %B %d at %I:%M %p')} for {duration_lbl}"
            )

            error_label.set_text("")
            step1_card.set_visibility(False)
            step2_card.set_visibility(True)

        def process_step2():
            if selected_room is None:
                ui.notify("Please select a room.", type="warning")
                return
            if not computed['start'] or not computed['end']:
                ui.notify("Something went wrong. Please try again.", type="negative")
                return

            success = make_reservation(session_user_id, selected_room, computed['start'], computed['end'])

            if success:
                step2_card.set_visibility(False)
                step3_card.set_visibility(True)
            else:
                ui.notify("That room was just booked. Please select another.", type="warning")


# ── /admin ─────────────────────────────────────────────────────────────────────

@ui.page('/admin')
def admin_page():
    if not require_login():
        return
    if current_role() != 'admin':
        with ui.column().classes("w-full items-center mt-16 gap-4"):
            ui.icon('lock', size='4rem').classes("text-red-700 opacity-50")
            ui.label("Access Denied").classes("text-3xl font-bold text-red-700")
            ui.label("You don't have permission to access this page.").classes("text-gray-600 text-lg")
            ui.button("← Back Home", on_click=lambda: ui.navigate.to("/")).classes("btn-cardinal px-8 py-3 rounded-lg mt-6")
        return

    render_nav_bar()

    admin_id = app.storage.user.get('user_id')

    with ui.column().classes("w-full max-w-6xl mx-auto px-6 gap-8 pb-12"):
        with ui.row().classes("items-center gap-4 mb-2"):
            ui.label("Pending Approvals").classes("text-4xl font-bold text-gray-900")
            count_badge = ui.badge("0", color="red")
        
        ui.label("Review and manage pending reservation requests.").classes("text-gray-600 text-lg mb-6")

        table_container = ui.column().classes("w-full gap-4")

        def refresh():
            table_container.clear()
            pending = get_pending_reservations()
            count_badge.set_text(str(len(pending)))
            
            with table_container:
                if not pending:
                    with ui.column().classes("items-center mt-16 gap-3"):
                        ui.icon('done_all', size='4rem').classes("text-green-500 opacity-70")
                        ui.label("All caught up!").classes("text-gray-700 text-xl font-semibold")
                        ui.label("No pending reservations.").classes("text-gray-500")
                    return
                
                for res in pending:
                    with ui.card().classes("w-full p-6 rounded-xl card-hover shadow-md bg-white border-l-4 border-red-500"):
                        with ui.row().classes("w-full items-start justify-between gap-6"):
                            with ui.column().classes("gap-3 flex-grow"):
                                with ui.row().classes("items-center gap-3"):
                                    ui.label(f"Reservation #{res['reservation_id']}").classes("text-lg font-bold text-gray-900")
                                    ui.badge("Pending", color="orange")
                                
                                ui.label(f"👤 {res['user_name']}").classes("text-gray-700 font-medium")
                                ui.label(f"📍 {res['room_name']}").classes("text-gray-600")
                                with ui.row().classes("gap-6 mt-2"):
                                    ui.label(f"📅 {res['start_datetime'].strftime('%a, %b %d')}").classes("text-gray-600 text-sm")
                                    ui.label(f"🕐 {res['start_datetime'].strftime('%I:%M %p')} - {res['end_datetime'].strftime('%I:%M %p')}").classes("text-gray-600 text-sm")
                            
                            with ui.row().classes("gap-3"):
                                rid = res['reservation_id']
                                ui.button("Approve", on_click=lambda r=rid: (approve_reservation(r, admin_id), refresh())).props("unelevated").classes("bg-green-600 text-white px-6 py-2 rounded-lg font-semibold")
                                ui.button("Reject", on_click=lambda r=rid: (reject_reservation(r, admin_id), refresh())).props("unelevated").classes("bg-red-600 text-white px-6 py-2 rounded-lg font-semibold")

        refresh()

        with ui.row().classes("justify-center mt-12"):
            ui.button("← Back to Home", on_click=lambda: ui.navigate.to("/")).props("outline").classes("btn-cardinal-outline px-8 py-3 rounded-lg text-base")


# ── Run ────────────────────────────────────────────────────────────────────────

ui.run(storage_secret='library-scheduler-secret-key', reload=False)
