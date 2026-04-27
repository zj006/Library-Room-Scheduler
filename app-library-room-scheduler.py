# Library Room Scheduling App

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
    cur.execute("""
        INSERT INTO reservation
        (reservation_id, user_id, room_id, start_datetime, end_datetime, purpose, attendee_count, status)
        VALUES (
            (SELECT COALESCE(MAX(reservation_id), 0) + 1 FROM reservation),
            %s, %s, %s, %s, 'General Use', 1, 'pending'
        )
    """, [user_id, room_id, start_datetime, end_datetime])
    conn.commit()


# ── Time slot helpers ──────────────────────────────────────────────────────────

def generate_time_options():
    """Generate every 30-minute slot across a full day."""
    options = []
    base = datetime(2000, 1, 1, 0, 0)
    for i in range(48):  # 48 half-hour slots
        t = base + timedelta(minutes=30 * i)
        options.append(t.strftime("%I:%M %p"))
    return options


def generate_duration_options():
    """30-min increments up to 4 hours."""
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
    """Combine a date string (YYYY-MM-DD) and time string (HH:MM AM/PM)."""
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %I:%M %p")


def duration_label_to_minutes(label: str) -> int:
    """Convert a duration label like '2 hrs 30 min' back to total minutes."""
    total = 0
    if 'hr' in label:
        parts = label.split('hr')
        total += int(parts[0].strip()) * 60
        if 'min' in parts[1]:
            total += int(parts[1].replace('min', '').strip())
    elif 'min' in label:
        total = int(label.replace('min', '').strip())
    return total


# ── Shared UI ──────────────────────────────────────────────────────────────────

def render_header():
    with ui.card().classes("w-full max-w-xl mx-auto p-6 shadow-lg border border-red-200 bg-gray-50"):
        with ui.column().classes("items-center"):
            ui.label("Library Room Scheduler").classes("text-h3 text-red-700 font-bold")
            ui.label("Reserve study spaces easily").classes("text-sm text-gray-600")


def render_nav_bar():
    with ui.row().classes("w-full justify-between items-center px-4 py-2 bg-gray-100 border-b mb-4"):
        name = app.storage.user.get('name', '')
        role = app.storage.user.get('role_name', '')
        ui.label(f"👤 {name}  ({role})").classes("text-sm text-gray-700")
        ui.button("Log Out", on_click=do_logout).classes("bg-red-600 text-white text-xs")


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

    with ui.card().classes("w-full max-w-sm mx-auto mt-8 p-6 shadow"):
        ui.label("Sign In").classes("text-h5 font-bold mb-2")

        email_box = ui.input("Email (.edu required)", placeholder="you@university.edu").classes("w-full")
        pass_box  = ui.input("Password", password=True, password_toggle_button=True).classes("w-full")
        error_label = ui.label("").classes("text-red-600 text-sm")

        def do_login():
            email = email_box.value.strip().lower()
            password = pass_box.value

            if not email.endswith('.edu'):
                error_label.set_text("Email must end with .edu")
                return

            user = get_user_by_email(email)
            if not user:
                error_label.set_text("No account found with that email.")
                return

            if user['password_hash'] != hash_password(password):
                error_label.set_text("Incorrect password.")
                return

            role_name = get_role_name(user['role_id'])
            app.storage.user.update({
                'user_id':   user['user_id'],
                'name':      user['name'],
                'email':     user['email'],
                'role_id':   user['role_id'],
                'role_name': role_name,
            })
            ui.navigate.to('/')

        ui.button("Sign In", on_click=do_login).classes("bg-black text-white w-full mt-2")
        ui.separator()
        ui.label("Don't have an account?").classes("text-sm text-gray-500 text-center")
        ui.button("Create Account", on_click=lambda: ui.navigate.to('/register')).classes(
            "bg-gray-200 text-black w-full"
        )


# ── /register ──────────────────────────────────────────────────────────────────

@ui.page('/register')
def register_page():
    render_header()

    with ui.card().classes("w-full max-w-sm mx-auto mt-8 p-6 shadow"):
        ui.label("Create Account").classes("text-h5 font-bold mb-2")

        name_box  = ui.input("Full Name").classes("w-full")
        email_box = ui.input("Email (.edu required)", placeholder="you@university.edu").classes("w-full")
        pass_box  = ui.input("Password", password=True, password_toggle_button=True).classes("w-full")
        pass_box2 = ui.input("Confirm Password", password=True, password_toggle_button=True).classes("w-full")

        role_select = ui.select(
            label="Role",
            options={"1": "Student", "2": "Admin"},
            value="1"
        ).classes("w-full")

        error_label = ui.label("").classes("text-red-600 text-sm")

        def do_register():
            name     = name_box.value.strip()
            email    = email_box.value.strip().lower()
            password = pass_box.value
            confirm  = pass_box2.value
            role_id  = int(role_select.value)

            if not name:
                error_label.set_text("Please enter your name.")
                return
            if not email.endswith('.edu'):
                error_label.set_text("Email must end with .edu")
                return
            if len(password) < 6:
                error_label.set_text("Password must be at least 6 characters.")
                return
            if password != confirm:
                error_label.set_text("Passwords do not match.")
                return
            if get_user_by_email(email):
                error_label.set_text("An account with that email already exists.")
                return

            create_user(name, email, password, role_id)
            ui.notify("Account created! Please sign in.", type="positive")
            ui.navigate.to('/login')

        ui.button("Create Account", on_click=do_register).classes("bg-black text-white w-full mt-2")
        ui.separator()
        ui.button("Back to Login", on_click=lambda: ui.navigate.to('/login')).classes(
            "bg-gray-200 text-black w-full"
        )


# ── / (homepage) ───────────────────────────────────────────────────────────────

@ui.page('/')
def homepage():
    if not require_login():
        return

    render_nav_bar()

    with ui.card().classes("w-full max-w-xl mx-auto p-6 shadow-lg"):
        with ui.column().classes("items-center"):
            ui.label("Library Room Scheduler").classes("text-h3 text-red-700 font-bold")
            ui.label(f"Welcome, {app.storage.user.get('name', '')}!").classes("text-sm text-gray-600")

    ui.label("Search available library rooms and make your reservations!")

    ui.button("View Rooms", on_click=lambda: ui.navigate.to("/rooms")).classes("bg-black text-white w-64")
    ui.button("Make a Reservation", on_click=lambda: ui.navigate.to("/reserve")).classes("bg-black text-white w-64")
    ui.button("View Reservations", on_click=lambda: ui.navigate.to("/reservations")).classes("bg-black text-white w-64")


# ── /rooms ─────────────────────────────────────────────────────────────────────

@ui.page('/rooms')
def rooms_page():
    if not require_login():
        return

    render_nav_bar()
    render_header()

    ui.label("All Rooms").classes("text-h4 text-center w-full mt-4")
    ui.label("Click reserve to check availability and book a time")

    rooms = get_rooms()
    booked_ids = get_booked_room_ids()

    with ui.column().classes("w-full max-w-4xl mx-auto gap-4 mt-4"):
        for room in rooms:
            is_booked = room['room_id'] in booked_ids
            with ui.card().classes("w-full p-4"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column():
                        ui.label(room['room_name']).classes("text-lg font-bold")
                        ui.label(f"Building: {room['building_name']}")
                        ui.label(f"Capacity: {room['capacity']}")
                        ui.label(f"Features: {room['features']}")
                        if is_booked:
                            ui.badge("Currently Unavailable", color="red").classes("mt-1")
                        else:
                            ui.badge("Available Now", color="green").classes("mt-1")

                    if is_booked:
                        ui.button("UNAVAILABLE", color="red").props("disabled")
                    else:
                        ui.button(
                            "RESERVE",
                            on_click=lambda room_id=room['room_id']: ui.navigate.to(f"/reserve?room_id={room_id}"),
                            color="green"
                        )

    with ui.row().classes("justify-center mt-6"):
        ui.button("Back Home", on_click=lambda: ui.navigate.to("/")).classes("bg-black text-white w-48")


# ── /reservations ──────────────────────────────────────────────────────────────

@ui.page('/reservations')
def reservations_page():
    if not require_login():
        return

    render_nav_bar()
    ui.label("Current Reservations").classes("text-h4")

    columns = [
        {'name': 'reservation_id', 'field': 'reservation_id', 'label': 'Reservation ID'},
        {'name': 'name',           'field': 'name',           'label': 'User'},
        {'name': 'room_name',      'field': 'room_name',      'label': 'Room'},
        {'name': 'start_datetime', 'field': 'start_datetime', 'label': 'Start'},
        {'name': 'end_datetime',   'field': 'end_datetime',   'label': 'End'},
        {'name': 'status',         'field': 'status',         'label': 'Status'},
    ]

    ui.table(columns=columns, rows=get_reservations())
    ui.button("Back Home", on_click=lambda: ui.navigate.to("/")).classes("bg-black text-white w-48 mt-4")


# ── /reserve ───────────────────────────────────────────────────────────────────

@ui.page('/reserve')
def reserve_page():
    if not require_login():
        return

    render_nav_bar()

    room_id = ui.context.client.request.query_params.get('room_id')
    selected_room = int(room_id) if room_id else None
    session_user_id = app.storage.user.get('user_id', '')

    time_options     = generate_time_options()
    duration_options = generate_duration_options()

    # Default start: next rounded 30-min slot
    now = datetime.now()
    default_date = now.strftime("%Y-%m-%d")
    rounded_min  = 30 * ((now.minute // 30) + 1)
    default_hour = now.hour + rounded_min // 60
    default_min  = rounded_min % 60
    default_time_str = datetime(2000, 1, 1, default_hour % 24, default_min).strftime("%I:%M %p")

    with ui.card() as step1_card:
        ui.label("Make a Reservation").classes("text-h5")
        if room_id:
            ui.label(f"Pre-selected Room ID: {room_id}").classes("text-green-600 font-bold")

        ui.label("Date:").classes("font-semibold mt-2")
        date_picker = ui.date(value=default_date).classes("w-full")

        ui.label("Start Time:").classes("font-semibold mt-2")
        start_select = ui.select(
            options=time_options,
            value=default_time_str if default_time_str in time_options else time_options[16]
        ).classes("w-full")

        ui.label("Duration (max 4 hours):").classes("font-semibold mt-2")
        duration_select = ui.select(
            options=duration_options,
            value=duration_options[1]  # default 1 hour
        ).classes("w-full")

        error_label = ui.label("").classes("text-red-600 text-sm mt-1")

        with ui.row().classes("gap-4 mt-4"):
            ui.button("Go Back", on_click=lambda: ui.navigate.to("/rooms")).props("color=black")
            ui.button("Search Available Rooms", on_click=lambda: process_step1()).props("color=green")

    with ui.card() as step2_card:
        ui.label("Available Rooms").classes("text-h5")
        ui.label("").classes("text-sm text-gray-500")  # will show selected time range

        columns = [
            {'name': 'room_id',       'field': 'room_id',       'label': 'Room ID'},
            {'name': 'room_name',     'field': 'room_name',      'label': 'Room Name'},
            {'name': 'building_name', 'field': 'building_name',  'label': 'Building'},
            {'name': 'capacity',      'field': 'capacity',       'label': 'Capacity'},
            {'name': 'features',      'field': 'features',       'label': 'Features'},
        ]
        rooms_table = ui.table(
            columns=columns, rows=[], selection='single',
            row_key='room_id', on_select=lambda e: click_room(e)
        )
        time_range_label = ui.label("").classes("text-sm text-gray-600 mt-2")

        with ui.row().classes("gap-4 mt-4"):
            ui.button("← Back", on_click=lambda: (
                step1_card.set_visibility(True),
                step2_card.set_visibility(False)
            )).props("color=black")
            ui.button("Reserve Selected Room", on_click=lambda: process_step2()).props("color=green")

    with ui.card() as step3_card:
        ui.label("Reservation Submitted!").classes("text-h5")
        ui.label("Your reservation is now pending approval.").classes("text-gray-600")
        ui.button("View Reservations", on_click=lambda: ui.navigate.to("/reservations")).classes("bg-green-600 text-white")
        ui.button("Back Home", on_click=lambda: ui.navigate.to("/")).props("color=black")

    step2_card.set_visibility(False)
    step3_card.set_visibility(False)

    # Store computed datetimes for step 2
    computed = {'start': None, 'end': None}

    def click_room(e):
        nonlocal selected_room
        if e.selection:
            selected_room = e.selection[0]['room_id']

    def process_step1():
        date_str     = date_picker.value
        time_str     = start_select.value
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

        # Double-check 4-hour max (shouldn't be possible via UI but just in case)
        if duration_mins > 240:
            error_label.set_text("Reservations cannot exceed 4 hours.")
            return

        if start_dt < datetime.now():
            error_label.set_text("Start time must be in the future.")
            return

        computed['start'] = start_dt
        computed['end']   = end_dt

        available_rooms = get_available_rooms(start_dt, end_dt)
        rooms_table.rows = available_rooms
        rooms_table.update()
        time_range_label.set_text(
            f"Showing rooms available from {start_dt.strftime('%b %d, %Y %I:%M %p')} "
            f"to {end_dt.strftime('%I:%M %p')} ({duration_lbl})"
        )

        error_label.set_text("")
        step1_card.set_visibility(False)
        step2_card.set_visibility(True)

    def process_step2():
        if selected_room is None:
            ui.notify("Please select a room first.")
            return
        if not computed['start'] or not computed['end']:
            ui.notify("Something went wrong. Please go back and try again.")
            return

        make_reservation(session_user_id, selected_room, computed['start'], computed['end'])
        step2_card.set_visibility(False)
        step3_card.set_visibility(True)


# ── Run ────────────────────────────────────────────────────────────────────────

ui.run(storage_secret='library-scheduler-secret-key', reload=False)