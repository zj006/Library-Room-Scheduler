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


# ── Global styles ──────────────────────────────────────────────────────────────

GLOBAL_STYLES = '''
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root { --q-primary: #9b1c1c; }
  body, .q-page { font-family: "Inter", sans-serif !important; background: #f3f4f6; }
  .card-hover { transition: box-shadow .2s ease, transform .15s ease; }
  .card-hover:hover { box-shadow: 0 10px 30px rgba(0,0,0,0.12); transform: translateY(-2px); }
  .q-date__header { background: #9b1c1c !important; }
  .q-date__header-link { color: #fff !important; }
  .q-date__calendar-item--active .q-btn { background: #9b1c1c !important; color: #fff !important; }
  .q-date__calendar-item .q-btn.text-primary { color: #9b1c1c !important; }
  .q-date__calendar-today .q-btn:before { border-color: #9b1c1c !important; }
  .q-date .q-btn.text-primary { color: #9b1c1c !important; }
</style>
'''

ui.add_head_html(GLOBAL_STYLES, shared=True)


def add_styles():
    ui.add_head_html(GLOBAL_STYLES)


# ── Shared UI ──────────────────────────────────────────────────────────────────

def render_header():
    with ui.column().classes('items-center w-full mt-12 mb-6 gap-1'):
        with ui.row().classes('items-center gap-2'):
            ui.icon('local_library', size='2rem').style('color: #9b1c1c')
            ui.label('Library Scheduler').classes('text-2xl font-bold text-gray-900 tracking-tight')
        ui.label('Reserve study spaces easily').classes('text-sm text-gray-500')


def render_nav_bar():
    add_styles()
    name = app.storage.user.get('name', '')
    role = app.storage.user.get('role_name', '')
    with ui.row().classes('w-full justify-between items-center px-8 py-4 bg-gray-900 mb-6').style('border-bottom: 3px solid #9b1c1c'):
        with ui.row().classes('items-center gap-3'):
            ui.icon('local_library', size='2rem').style('color: #9b1c1c')
            ui.label('Library Scheduler').classes('text-white font-semibold text-base')
        with ui.row().classes('items-center gap-4'):
            with ui.button('').props('flat no-caps').classes('rounded-full p-0').style('background:transparent'):
                with ui.row().classes('items-center gap-2 px-3 py-2 rounded-full').style('background:#1f2937; border: 1px solid #374151; transition: background .2s'):
                    with ui.element('div').classes('w-8 h-8 rounded-full flex items-center justify-center').style('background:#9b1c1c'):
                        ui.label(name[0].upper() if name else '?').classes('text-white font-bold text-sm')
                    with ui.column().classes('gap-0 items-start'):
                        ui.label(name).classes('text-white text-xs font-semibold leading-tight')
                        ui.label(role.capitalize()).classes('text-xs leading-tight').style('color:#9b1c1c')
                    ui.icon('expand_more', size='1rem').classes('text-gray-400')
                with ui.menu().props('auto-close').classes('rounded-xl shadow-xl').style('min-width:180px; margin-top:4px'):
                    with ui.element('div').classes('px-4 py-3').style('border-bottom: 1px solid #f3f4f6'):
                        ui.label(name).classes('text-sm font-semibold text-gray-900')
                        ui.label(role.capitalize()).classes('text-xs text-gray-400')
                    with ui.item(on_click=lambda: ui.navigate.to('/account')).classes('cursor-pointer'):
                        with ui.item_section().props('avatar'):
                            ui.icon('manage_accounts', size='1.1rem').classes('text-gray-500')
                        with ui.item_section():
                            ui.label('Account Settings').classes('text-sm text-gray-700')
                    ui.separator()
                    with ui.item(on_click=do_logout).classes('cursor-pointer'):
                        with ui.item_section().props('avatar'):
                            ui.icon('logout', size='1.1rem').style('color:#ef4444')
                        with ui.item_section():
                            ui.label('Log Out').classes('text-sm text-red-500')


def do_logout():
    app.storage.user.clear()
    ui.navigate.to('/login')


# ── /login ─────────────────────────────────────────────────────────────────────

@ui.page('/login')
def login_page():
    add_styles()
    if is_logged_in():
        ui.navigate.to('/')
        return

    render_header()

    with ui.card().classes('w-full max-w-sm mx-auto rounded-2xl shadow-lg p-8'):
        ui.label('Sign In').classes('text-xl font-bold text-gray-900 mb-1 text-center w-full')
        ui.label('Welcome back — enter your credentials below.').classes('text-xs text-gray-500 mb-5 text-center w-full')

        email_box = ui.input('Email', placeholder='you@university.edu').props('outlined dense').classes('w-full mb-3')
        pass_box  = ui.input('Password', password=True, password_toggle_button=True).props('outlined dense').classes('w-full')
        error_label = ui.label('').classes('text-red-500 text-xs mt-2 min-h-[1rem]')

        def do_login():
            email    = email_box.value.strip().lower()
            password = pass_box.value

            if not email.endswith('.edu'):
                error_label.set_text('Email must end with .edu')
                return

            user = get_user_by_email(email)
            if not user:
                error_label.set_text('No account found with that email.')
                return

            if user['password_hash'] != hash_password(password):
                error_label.set_text('Incorrect password.')
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

        ui.button('Sign In', on_click=do_login).props('color=primary no-caps unelevated').classes('w-full mt-4 rounded-lg font-semibold')
        ui.separator().classes('my-4')
        ui.label("Don't have an account?").classes('text-xs text-gray-500 text-center mb-2')
        ui.button('Create Account', on_click=lambda: ui.navigate.to('/register')).props('color=primary outline no-caps').classes('w-full rounded-lg font-medium')


# ── /register ──────────────────────────────────────────────────────────────────

@ui.page('/register')
def register_page():
    add_styles()
    render_header()

    with ui.card().classes('w-full max-w-sm mx-auto rounded-2xl shadow-lg p-8'):
        ui.label('Create Account').classes('text-xl font-bold text-gray-900 mb-1 text-center w-full')
        ui.label('Fill in your details to get started.').classes('text-xs text-gray-500 mb-5 text-center w-full')

        with ui.row().classes('w-full gap-3 mb-3'):
            first_name_box = ui.input('First Name').props('outlined dense').classes('flex-1')
            last_name_box  = ui.input('Last Name').props('outlined dense').classes('flex-1')
        email_box = ui.input('Email', placeholder='you@university.edu').props('outlined dense').classes('w-full mb-3')
        pass_box  = ui.input('Password', password=True, password_toggle_button=True).props('outlined dense').classes('w-full mb-3')
        pass_box2 = ui.input('Confirm Password', password=True, password_toggle_button=True).props('outlined dense').classes('w-full')

        role_select = ui.select(
            label='Role',
            options={'1': 'Student', '2': 'Admin'},
            value='1'
        ).props('outlined dense').classes('w-full mt-3')

        error_label = ui.label('').classes('text-red-500 text-xs mt-2 min-h-[1rem]')

        def do_register():
            first    = first_name_box.value.strip()
            last     = last_name_box.value.strip()
            name     = f'{first} {last}'
            email    = email_box.value.strip().lower()
            password = pass_box.value
            confirm  = pass_box2.value
            role_id  = int(role_select.value)

            if not first or not last:
                error_label.set_text('Please enter your first and last name.')
                return
            if not email.endswith('.edu'):
                error_label.set_text('Email must end with .edu')
                return
            if len(password) < 6:
                error_label.set_text('Password must be at least 6 characters.')
                return
            if password != confirm:
                error_label.set_text('Passwords do not match.')
                return
            if get_user_by_email(email):
                error_label.set_text('An account with that email already exists.')
                return

            create_user(name, email, password, role_id)
            ui.notify('Account created! Please sign in.', type='positive')
            ui.navigate.to('/login')

        ui.button('Create Account', on_click=do_register).props('color=primary no-caps unelevated').classes('w-full mt-4 rounded-lg font-semibold')
        ui.separator().classes('my-4')
        ui.button('Back to Sign In', on_click=lambda: ui.navigate.to('/login')).props('color=primary outline no-caps').classes('w-full rounded-lg font-medium')


# ── / (homepage) ───────────────────────────────────────────────────────────────

@ui.page('/')
def homepage():
    if not require_login():
        return

    render_nav_bar()

    available_count = len(get_rooms()) - len(get_booked_room_ids())
    name = app.storage.user.get('name', '')
    role = app.storage.user.get('role_name', '')

    with ui.column().classes('w-full max-w-3xl mx-auto px-4 gap-5'):
        # Hero banner
        with ui.element('div').classes('w-full rounded-2xl p-8').style('background: linear-gradient(135deg, #9b1c1c 0%, #7f1d1d 100%)'):
            ui.label(f'Welcome back, {name}').classes('text-white text-2xl font-bold')
            ui.label(f'{available_count} room{"s" if available_count != 1 else ""} available right now').classes('text-white text-sm mt-1').style('opacity:0.8')

        # Nav cards
        nav_items = [
            ('meeting_room', 'Browse Rooms',      'View all available study spaces', '/rooms'),
            ('event',        'Make a Reservation','Book a room for your session',     '/reserve'),
            ('list_alt',     'My Reservations',   'View and track your bookings',     '/reservations'),
        ]

        with ui.grid(columns=3).classes('w-full gap-4'):
            for icon_name, title, subtitle, route in nav_items:
                with ui.card().classes('card-hover rounded-2xl p-6 bg-white shadow-sm border border-gray-100 cursor-pointer').on('click', lambda r=route: ui.navigate.to(r)):
                    ui.icon(icon_name, size='2rem').style('color: #9b1c1c')
                    ui.label(title).classes('text-gray-900 font-semibold text-sm mt-3')
                    ui.label(subtitle).classes('text-gray-500 text-xs mt-1')

        if role == 'admin':
            with ui.card().classes('card-hover w-full rounded-2xl p-5 bg-white shadow-sm border border-gray-100 cursor-pointer').style('border-left: 4px solid #9b1c1c').on('click', lambda: ui.navigate.to('/admin')):
                with ui.row().classes('items-center gap-4'):
                    ui.icon('admin_panel_settings', size='2rem').style('color: #9b1c1c')
                    with ui.column().classes('gap-0'):
                        ui.label('Admin Panel').classes('text-gray-900 font-semibold text-sm')
                        ui.label('Review and manage pending reservations').classes('text-gray-500 text-xs')


# ── /rooms ─────────────────────────────────────────────────────────────────────

@ui.page('/rooms')
def rooms_page():
    if not require_login():
        return

    render_nav_bar()

    with ui.column().classes('w-full max-w-4xl mx-auto px-4 gap-4'):
        with ui.row().classes('items-center justify-between w-full'):
            with ui.column().classes('gap-0'):
                ui.label('All Rooms').classes('text-xl font-bold text-gray-900')
                ui.label('Click Reserve to check availability and book a time.').classes('text-sm text-gray-500')

        rooms = get_rooms()
        booked_ids = get_booked_room_ids()

        search_input = ui.input(placeholder='Search by room name or building...').props('outlined dense clearable').classes('w-full')

        room_container = ui.column().classes('w-full gap-3 mt-1')

        def render_rooms(filter_text=''):
            room_container.clear()
            q = filter_text.strip().lower()
            filtered = [r for r in rooms if not q or q in r['room_name'].lower() or q in (r['building_name'] or '').lower()]
            with room_container:
                if not filtered:
                    with ui.column().classes('items-center mt-10 gap-2'):
                        ui.icon('search_off', size='3rem').classes('text-gray-300')
                        ui.label('No rooms match your search.').classes('text-gray-400')
                    return
                for room in filtered:
                    is_booked = room['room_id'] in booked_ids
                    accent = 'border-red-400' if is_booked else 'border-green-500'
                    with ui.card().classes(f'w-full rounded-xl bg-white shadow-sm border-l-4 {accent}'):
                        with ui.row().classes('w-full items-center justify-between p-4'):
                            with ui.column().classes('gap-1'):
                                ui.label(room['room_name']).classes('text-gray-900 font-semibold text-base')
                                with ui.row().classes('gap-4 flex-wrap'):
                                    ui.label(f"Building: {room['building_name']}").classes('text-gray-500 text-xs')
                                    ui.label(f"Capacity: {room['capacity']}").classes('text-gray-500 text-xs')
                                if room['features']:
                                    ui.label(f"Features: {room['features']}").classes('text-gray-500 text-xs')
                                if is_booked:
                                    ui.badge('Unavailable', color='red').classes('mt-1 text-xs')
                                else:
                                    ui.badge('Available', color='green').classes('mt-1 text-xs')
                            if is_booked:
                                ui.button('Unavailable').props('color=grey disabled no-caps unelevated').classes('rounded-lg px-4 text-xs font-medium')
                            else:
                                ui.button(
                                    'Reserve',
                                    on_click=lambda rid=room['room_id']: ui.navigate.to(f'/reserve?room_id={rid}')
                                ).props('color=primary no-caps unelevated').classes('rounded-lg px-4 text-xs font-medium')

        search_input.on('input', lambda: render_rooms(search_input.value))
        render_rooms()

        ui.button('Back Home', on_click=lambda: ui.navigate.to('/')).props('color=primary outline no-caps').classes('rounded-lg mt-2')


# ── /reservations ──────────────────────────────────────────────────────────────

@ui.page('/reservations')
def reservations_page():
    if not require_login():
        return

    render_nav_bar()

    with ui.column().classes('w-full max-w-5xl mx-auto px-4 gap-5'):
        if current_role() == 'admin':
            ui.label('All Reservations').classes('text-xl font-bold text-gray-900')
            columns = [
                {'name': 'reservation_id', 'field': 'reservation_id', 'label': 'ID', 'align': 'left'},
                {'name': 'name',           'field': 'name',           'label': 'User', 'align': 'left'},
                {'name': 'room_name',      'field': 'room_name',      'label': 'Room', 'align': 'left'},
                {'name': 'start_datetime', 'field': 'start_datetime', 'label': 'Start', 'align': 'left'},
                {'name': 'end_datetime',   'field': 'end_datetime',   'label': 'End', 'align': 'left'},
                {'name': 'status',         'field': 'status',         'label': 'Status', 'align': 'left'},
            ]
            rows = get_reservations()
        else:
            ui.label('My Reservations').classes('text-xl font-bold text-gray-900')
            columns = [
                {'name': 'reservation_id', 'field': 'reservation_id', 'label': 'ID', 'align': 'left'},
                {'name': 'room_name',      'field': 'room_name',      'label': 'Room', 'align': 'left'},
                {'name': 'start_datetime', 'field': 'start_datetime', 'label': 'Start', 'align': 'left'},
                {'name': 'end_datetime',   'field': 'end_datetime',   'label': 'End', 'align': 'left'},
                {'name': 'status',         'field': 'status',         'label': 'Status', 'align': 'left'},
            ]
            rows = get_user_reservations(app.storage.user['user_id'])

        with ui.card().classes('w-full rounded-2xl shadow-sm bg-white p-2'):
            table = ui.table(columns=columns, rows=rows).classes('w-full')
            table.add_slot('body-cell-status', '''
                <q-td :props="props">
                    <q-badge
                        :color="props.value === 'approved' ? 'green' : props.value === 'rejected' ? 'red' : 'orange'"
                        :label="props.value"
                    />
                </q-td>
            ''')

        ui.separator().classes('my-2')
        ui.label('Room Usage Summary').classes('text-base font-bold text-gray-900')

        stats_columns = [
            {'name': 'room_name',          'field': 'room_name',          'label': 'Room',     'align': 'left'},
            {'name': 'total_reservations', 'field': 'total_reservations', 'label': 'Total',    'align': 'center'},
            {'name': 'approved',           'field': 'approved',           'label': 'Approved', 'align': 'center'},
            {'name': 'pending',            'field': 'pending',            'label': 'Pending',  'align': 'center'},
            {'name': 'rejected',           'field': 'rejected',           'label': 'Rejected', 'align': 'center'},
        ]
        with ui.card().classes('w-full rounded-2xl shadow-sm bg-white p-2'):
            ui.table(columns=stats_columns, rows=get_reservation_stats()).classes('w-full')

        ui.button('Back Home', on_click=lambda: ui.navigate.to('/')).props('color=primary outline no-caps').classes('rounded-lg mt-2')


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

    now = datetime.now()
    default_date = now.strftime('%Y-%m-%d')
    rounded_min  = 30 * ((now.minute // 30) + 1)
    default_hour = now.hour + rounded_min // 60
    default_min  = rounded_min % 60
    default_time_str = datetime(2000, 1, 1, default_hour % 24, default_min).strftime('%I:%M %p')

    with ui.column().classes('w-full max-w-2xl mx-auto px-4 gap-5'):

        # Step indicator
        def step_badge(n, active=False):
            bg = '#9b1c1c' if active else '#e5e7eb'
            color = 'text-white' if active else 'text-gray-400'
            with ui.element('div').classes(f'w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0').style(f'background:{bg}'):
                ui.label(str(n)).classes(f'{color} font-bold text-sm')

        with ui.row().classes('items-center gap-2 w-full') as step_row:
            s1_badge_wrap = ui.element('div').classes('flex items-center gap-2')
            with s1_badge_wrap:
                step_badge(1, active=True)
                ui.label('Select Time').classes('text-gray-900 font-semibold text-sm')
            ui.element('div').classes('flex-1 h-px bg-gray-200')
            s2_badge_wrap = ui.element('div').classes('flex items-center gap-2')
            with s2_badge_wrap:
                step_badge(2, active=False)
                ui.label('Choose Room').classes('text-gray-400 text-sm')
            ui.element('div').classes('flex-1 h-px bg-gray-200')
            s3_badge_wrap = ui.element('div').classes('flex items-center gap-2')
            with s3_badge_wrap:
                step_badge(3, active=False)
                ui.label('Confirmed').classes('text-gray-400 text-sm')

        # Step 1
        with ui.card().classes('w-full rounded-2xl shadow-sm bg-white p-6') as step1_card:
            ui.label('Make a Reservation').classes('text-lg font-bold text-gray-900 mb-1')
            if room_id:
                with ui.row().classes('items-center gap-1 mb-3'):
                    ui.icon('check_circle', size='1rem').style('color:#16a34a')
                    ui.label(f'Pre-selected Room ID: {room_id}').classes('text-green-700 text-xs font-semibold')

            ui.label('Date').classes('text-xs font-semibold text-gray-700 mt-3 mb-1')
            date_picker = ui.date(value=default_date).classes('w-full')

            ui.label('Start Time').classes('text-xs font-semibold text-gray-700 mt-4 mb-1')
            start_select = ui.select(
                options=time_options,
                value=default_time_str if default_time_str in time_options else time_options[16]
            ).props('outlined dense').classes('w-full')

            ui.label('Duration (max 4 hours)').classes('text-xs font-semibold text-gray-700 mt-3 mb-1')
            duration_select = ui.select(
                options=duration_options,
                value=duration_options[1]
            ).props('outlined dense').classes('w-full')

            error_label = ui.label('').classes('text-red-500 text-xs mt-2 min-h-[1rem]')

            with ui.row().classes('gap-3 mt-5'):
                ui.button('Back Home', on_click=lambda: ui.navigate.to('/')).props('color=primary outline no-caps').classes('rounded-lg')
                ui.button('Search Available Rooms', on_click=lambda: process_step1()).props('color=primary no-caps unelevated').classes('rounded-lg font-semibold')

        # Step 2
        with ui.card().classes('w-full rounded-2xl shadow-sm bg-white p-6') as step2_card:
            ui.label('Available Rooms').classes('text-lg font-bold text-gray-900 mb-1')
            time_range_label = ui.label('').classes('text-xs text-gray-500 mb-3')

            columns = [
                {'name': 'room_id',       'field': 'room_id',       'label': 'ID',       'align': 'left'},
                {'name': 'room_name',     'field': 'room_name',     'label': 'Room',      'align': 'left'},
                {'name': 'building_name', 'field': 'building_name', 'label': 'Building',  'align': 'left'},
                {'name': 'capacity',      'field': 'capacity',      'label': 'Capacity',  'align': 'center'},
                {'name': 'features',      'field': 'features',      'label': 'Features',  'align': 'left'},
            ]
            rooms_table = ui.table(
                columns=columns, rows=[], selection='single',
                row_key='room_id', on_select=lambda e: click_room(e)
            ).classes('w-full')

            with ui.row().classes('gap-3 mt-5'):
                def go_back():
                    step1_card.set_visibility(True)
                    step2_card.set_visibility(False)
                ui.button('← Back', on_click=go_back).props('color=primary outline no-caps').classes('rounded-lg')
                ui.button('Reserve Selected Room', on_click=lambda: process_step2()).props('color=positive no-caps unelevated').classes('rounded-lg font-semibold')

        # Step 3
        with ui.card().classes('w-full rounded-2xl shadow-sm bg-white p-8 items-center text-center') as step3_card:
            ui.icon('check_circle', size='3rem').style('color:#16a34a')
            ui.label('Reservation Submitted!').classes('text-lg font-bold text-gray-900 mt-3')
            ui.label('Your reservation is now pending approval.').classes('text-sm text-gray-500 mt-1 mb-5')
            with ui.row().classes('justify-center gap-3'):
                ui.button('View My Reservations', on_click=lambda: ui.navigate.to('/reservations')).props('color=primary no-caps unelevated').classes('rounded-lg font-semibold')
                ui.button('Back Home', on_click=lambda: ui.navigate.to('/')).props('color=primary outline no-caps').classes('rounded-lg')

    step2_card.set_visibility(False)
    step3_card.set_visibility(False)

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
            error_label.set_text('Please select a date.')
            return

        try:
            start_dt = parse_datetime(date_str, time_str)
        except Exception:
            error_label.set_text('Invalid date or time selection.')
            return

        duration_mins = duration_label_to_minutes(duration_lbl)
        end_dt = start_dt + timedelta(minutes=duration_mins)

        if duration_mins > 240:
            error_label.set_text('Reservations cannot exceed 4 hours.')
            return

        if start_dt < datetime.now():
            error_label.set_text('Start time must be in the future.')
            return

        computed['start'] = start_dt
        computed['end']   = end_dt

        available_rooms = get_available_rooms(start_dt, end_dt)
        rooms_table.rows = available_rooms
        rooms_table.update()
        time_range_label.set_text(
            f"Rooms available from {start_dt.strftime('%b %d, %Y %I:%M %p')} "
            f"to {end_dt.strftime('%I:%M %p')} ({duration_lbl})"
        )

        error_label.set_text('')
        step1_card.set_visibility(False)
        step2_card.set_visibility(True)

    def process_step2():
        if selected_room is None:
            ui.notify('Please select a room first.', type='warning')
            return
        if not computed['start'] or not computed['end']:
            ui.notify('Something went wrong. Please go back and try again.', type='negative')
            return

        success = make_reservation(session_user_id, selected_room, computed['start'], computed['end'])

        if success:
            step2_card.set_visibility(False)
            step3_card.set_visibility(True)
        else:
            ui.notify('Sorry, that room was just booked by someone else. Please select another.', type='warning')


# ── /account ───────────────────────────────────────────────────────────────────

@ui.page('/account')
def account_page():
    if not require_login():
        return

    render_nav_bar()

    user_id = app.storage.user.get('user_id')
    current_name  = app.storage.user.get('name', '')
    current_email = app.storage.user.get('email', '')
    current_role  = app.storage.user.get('role_name', '')

    name_parts = current_name.split(' ', 1)
    current_first = name_parts[0]
    current_last  = name_parts[1] if len(name_parts) > 1 else ''

    with ui.column().classes('w-full max-w-lg mx-auto px-4 gap-4'):

        # Page heading
        with ui.column().classes('gap-0'):
            ui.label('Account Settings').classes('text-xl font-bold text-gray-900')
            ui.label('Manage your profile and security settings.').classes('text-sm text-gray-500')

        # Profile summary card
        with ui.card().classes('w-full rounded-2xl shadow-sm bg-white p-5'):
            with ui.row().classes('items-center gap-4'):
                with ui.element('div').classes('w-14 h-14 rounded-full flex items-center justify-center flex-shrink-0').style('background:#9b1c1c'):
                    ui.label(current_name[0].upper() if current_name else '?').classes('text-white font-bold text-xl')
                with ui.column().classes('gap-0'):
                    ui.label(current_name).classes('text-gray-900 font-semibold text-base')
                    ui.label(current_email).classes('text-gray-500 text-xs mt-0.5')
                    with ui.element('div').classes('rounded-full px-2 py-0.5 mt-1').style('background:#fef2f2; display:inline-block'):
                        ui.label(current_role.capitalize()).classes('text-xs font-semibold').style('color:#9b1c1c')

        # Update name card
        with ui.card().classes('w-full rounded-2xl shadow-sm bg-white p-6'):
            with ui.row().classes('items-center gap-2 mb-4'):
                ui.icon('badge', size='1.2rem').classes('text-gray-400')
                ui.label('Update Name').classes('text-sm font-semibold text-gray-700')

            with ui.row().classes('w-full gap-3'):
                first_name_box = ui.input('First Name', value=current_first).props('outlined dense').classes('flex-1')
                last_name_box  = ui.input('Last Name',  value=current_last).props('outlined dense').classes('flex-1')
            name_error = ui.label('').classes('text-red-500 text-xs mt-1 min-h-[1rem]')

        # Change email card
        with ui.card().classes('w-full rounded-2xl shadow-sm bg-white p-6'):
            with ui.row().classes('items-center gap-2 mb-4'):
                ui.icon('email', size='1.2rem').classes('text-gray-400')
                ui.label('Change Email').classes('text-sm font-semibold text-gray-700')

            email_box  = ui.input('New Email', placeholder='you@university.edu', value=current_email).props('outlined dense').classes('w-full')
            email_error = ui.label('').classes('text-red-500 text-xs mt-1 min-h-[1rem]')

        # Change password card
        with ui.card().classes('w-full rounded-2xl shadow-sm bg-white p-6'):
            with ui.row().classes('items-center gap-2 mb-4'):
                ui.icon('lock', size='1.2rem').classes('text-gray-400')
                ui.label('Change Password').classes('text-sm font-semibold text-gray-700')

            new_pass_box     = ui.input('New Password', password=True, password_toggle_button=True).props('outlined dense autocomplete=new-password').classes('w-full mb-3')
            confirm_pass_box = ui.input('Confirm New Password', password=True, password_toggle_button=True).props('outlined dense autocomplete=new-password').classes('w-full')
            pass_error = ui.label('').classes('text-red-500 text-xs mt-1 min-h-[1rem]')

        # Confirmation dialog
        with ui.dialog() as confirm_dialog, ui.card().classes('rounded-2xl p-6 w-80'):
            ui.label('Save Changes?').classes('text-base font-bold text-gray-900 mb-1')
            ui.label('Are you sure you want to update your account settings?').classes('text-sm text-gray-500 mb-4')
            with ui.row().classes('justify-end gap-3 w-full'):
                ui.button('Cancel', on_click=confirm_dialog.close).props('flat no-caps').classes('text-gray-500')
                ui.button('Confirm', on_click=lambda: (do_save(), confirm_dialog.close())).props('color=primary no-caps unelevated').classes('rounded-lg font-semibold')

        def validate():
            name_error.set_text('')
            email_error.set_text('')
            pass_error.set_text('')

            first = first_name_box.value.strip()
            last  = last_name_box.value.strip()
            if not first or not last:
                name_error.set_text('Please enter both first and last name.')
                return False

            new_email = email_box.value.strip().lower()
            if not new_email.endswith('.edu'):
                email_error.set_text('Email must end with .edu')
                return False
            if new_email != current_email and get_user_by_email(new_email):
                email_error.set_text('An account with that email already exists.')
                return False

            new_pass = new_pass_box.value
            confirm  = confirm_pass_box.value
            if new_pass or confirm:
                if len(new_pass) < 6:
                    pass_error.set_text('Password must be at least 6 characters.')
                    return False
                if new_pass != confirm:
                    pass_error.set_text('Passwords do not match.')
                    return False

            return True

        def do_save():
            first     = first_name_box.value.strip()
            last      = last_name_box.value.strip()
            new_name  = f'{first} {last}'
            new_email = email_box.value.strip().lower()
            new_pass  = new_pass_box.value

            cur.execute("UPDATE useraccount SET name = %s, email = %s WHERE user_id = %s", [new_name, new_email, user_id])
            if new_pass:
                cur.execute("UPDATE useraccount SET password_hash = %s WHERE user_id = %s", [hash_password(new_pass), user_id])
            conn.commit()

            app.storage.user['name']  = new_name
            app.storage.user['email'] = new_email
            new_pass_box.value = ''
            confirm_pass_box.value = ''
            ui.notify('Settings saved successfully.', type='positive')
            ui.timer(2.0, lambda: ui.navigate.to('/'), once=True)

        def on_save_click():
            if validate():
                confirm_dialog.open()

        # Bottom action row
        with ui.row().classes('w-full justify-between items-center mt-1'):
            ui.button('Back Home', on_click=lambda: ui.navigate.to('/')).props('color=primary outline no-caps').classes('rounded-lg')
            ui.button('Save Changes', on_click=on_save_click).props('color=primary no-caps unelevated').classes('rounded-lg font-semibold')


# ── /admin ─────────────────────────────────────────────────────────────────────

@ui.page('/admin')
def admin_page():
    if not require_login():
        return
    if current_role() != 'admin':
        with ui.column().classes('items-center mt-16 gap-3'):
            ui.icon('lock', size='3rem').classes('text-gray-300')
            ui.label('Access Denied').classes('text-xl font-bold text-gray-700')
            ui.button('Back Home', on_click=lambda: ui.navigate.to('/')).props('color=primary outline no-caps').classes('rounded-lg mt-2')
        return

    render_nav_bar()

    admin_id = app.storage.user.get('user_id')

    with ui.column().classes('w-full max-w-5xl mx-auto px-4 gap-4'):
        with ui.row().classes('items-center gap-3'):
            ui.label('Admin Panel').classes('text-xl font-bold text-gray-900')
            count_badge = ui.badge('0', color='red')
        ui.label('Review and action pending reservations below.').classes('text-sm text-gray-500')

        table_container = ui.column().classes('w-full gap-3')

        def refresh():
            table_container.clear()
            pending = get_pending_reservations()
            count_badge.set_text(str(len(pending)))
            with table_container:
                if not pending:
                    with ui.column().classes('items-center mt-10 gap-2'):
                        ui.icon('check_circle', size='3rem').classes('text-gray-300')
                        ui.label('No pending reservations.').classes('text-gray-400')
                    return
                for res in pending:
                    with ui.card().classes('w-full rounded-xl bg-white shadow-sm border-l-4 border-yellow-400'):
                        with ui.row().classes('w-full items-center justify-between p-4'):
                            with ui.column().classes('gap-1'):
                                ui.label(f"Reservation #{res['reservation_id']}").classes('text-gray-900 font-semibold text-sm')
                                with ui.row().classes('gap-4 flex-wrap'):
                                    ui.label(f"User: {res['user_name']}").classes('text-gray-500 text-xs')
                                    ui.label(f"Room: {res['room_name']}").classes('text-gray-500 text-xs')
                                ui.label(f"From: {res['start_datetime'].strftime('%b %d, %Y %I:%M %p')}  →  {res['end_datetime'].strftime('%I:%M %p')}").classes('text-gray-500 text-xs')
                            with ui.row().classes('gap-2'):
                                rid = res['reservation_id']
                                ui.button('Approve', on_click=lambda r=rid: (approve_reservation(r, admin_id), refresh())).props('color=positive no-caps unelevated').classes('rounded-lg px-4 text-xs font-medium')
                                ui.button('Reject',  on_click=lambda r=rid: (reject_reservation(r, admin_id),  refresh())).props('color=negative no-caps unelevated').classes('rounded-lg px-4 text-xs font-medium')

        refresh()

        ui.button('Back Home', on_click=lambda: ui.navigate.to('/')).props('color=primary outline no-caps').classes('rounded-lg mt-2')


# ── Run ────────────────────────────────────────────────────────────────────────

ui.run(storage_secret='library-scheduler-secret-key', reload=False)
