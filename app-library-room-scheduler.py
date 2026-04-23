# Library Room Scheduling App

import psycopg
from psycopg.rows import dict_row
from dbinfo import *
from nicegui import ui

# Connect to database
conn = psycopg.connect(
    f"host=dbclass.rhodescs.org dbname=practice user={DBUSER} password={DBPASS}"
)

cur = conn.cursor(row_factory=dict_row)


def get_rooms():
    cur.execute("""
        SELECT room_id, room_name, capacity
        FROM room
        ORDER BY room_id
    """)
    return cur.fetchall()


def get_reservations():
    cur.execute("""
        SELECT reservation.reservation_id,
               useraccount.name,
               room.room_name,
               reservation.start_datetime,
               reservation.end_datetime,
               reservation.status
        FROM reservation
        JOIN useraccount ON reservation.user_id = useraccount.user_id
        JOIN room ON reservation.room_id = room.room_id
        ORDER BY reservation.start_datetime
    """)
    return cur.fetchall()


def get_available_rooms(start_datetime, end_datetime):
    cur.execute("""
        SELECT room_id, room_name, capacity
        FROM room
        WHERE room_id NOT IN (
            SELECT room_id
            FROM reservation
            WHERE status IN ('approved', 'pending')
              AND start_datetime < %s
              AND end_datetime > %s
        )
        ORDER BY room_id
    """, [end_datetime, start_datetime])
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


@ui.page('/')
def homepage():
    ui.label("Library Room Scheduler").classes("text-h4")
    ui.label("Search available library rooms and make reservations.")

    ui.link("View Rooms", "/rooms")
    ui.link("Make a Reservation", "/reserve")
    ui.link("View Reservations", "/reservations")


@ui.page('/rooms')
def rooms_page():
    ui.label("Library Rooms").classes("text-h4")

    columns = [
        {'name': 'room_id', 'field': 'room_id', 'label': 'Room ID'},
        {'name': 'room_name', 'field': 'room_name', 'label': 'Room Name'},
        {'name': 'capacity', 'field': 'capacity', 'label': 'Capacity'},
    ]

    ui.table(columns=columns, rows=get_rooms())

    ui.link("Back Home", "/")


@ui.page('/reservations')
def reservations_page():
    ui.label("Current Reservations").classes("text-h4")

    columns = [
        {'name': 'reservation_id', 'field': 'reservation_id', 'label': 'Reservation ID'},
        {'name': 'name', 'field': 'name', 'label': 'User'},
        {'name': 'room_name', 'field': 'room_name', 'label': 'Room'},
        {'name': 'start_datetime', 'field': 'start_datetime', 'label': 'Start'},
        {'name': 'end_datetime', 'field': 'end_datetime', 'label': 'End'},
        {'name': 'status', 'field': 'status', 'label': 'Status'},
    ]

    ui.table(columns=columns, rows=get_reservations())

    ui.link("Back Home", "/")


@ui.page('/reserve')
def reserve_page():
    selected_room = None

    with ui.card() as step1_card:
        ui.label("Search for Available Rooms").classes("text-h5")

        with ui.row():
            ui.label("User ID:")
            user_id_box = ui.input()

        with ui.row():
            ui.label("Start (YYYY-MM-DD HH:MM):")
            start_box = ui.input(placeholder="2026-04-15 10:00")

        with ui.row():
            ui.label("End (YYYY-MM-DD HH:MM):")
            end_box = ui.input(placeholder="2026-04-15 11:00")

        ui.button("Find Available Rooms", on_click=lambda: process_step1())

    with ui.card() as step2_card:
        ui.label("Available Rooms").classes("text-h5")

        columns = [
            {'name': 'room_id', 'field': 'room_id', 'label': 'Room ID'},
            {'name': 'room_name', 'field': 'room_name', 'label': 'Room Name'},
            {'name': 'capacity', 'field': 'capacity', 'label': 'Capacity'},
        ]

        rooms_table = ui.table(
            columns=columns,
            rows=[],
            selection='single',
            row_key='room_id',
            on_select=lambda e: click_room(e)
        )

        ui.button("Reserve Selected Room", on_click=lambda: process_step2())

    with ui.card() as step3_card:
        ui.label("Reservation Submitted!").classes("text-h5")
        ui.label("Your reservation is now pending.")
        ui.link("View Reservations", "/reservations")
        ui.link("Back Home", "/")

    step2_card.set_visibility(False)
    step3_card.set_visibility(False)

    def click_room(e):
        nonlocal selected_room
        if len(e.selection) > 0:
            selected_room = e.selection[0]['room_id']

    def process_step1():
        available_rooms = get_available_rooms(
            start_box.value,
            end_box.value
        )

        rooms_table.rows = available_rooms
        rooms_table.update()

        step1_card.set_visibility(False)
        step2_card.set_visibility(True)

    def process_step2():
        if selected_room is None:
            ui.notify("Please select a room first.")
            return

        make_reservation(
            user_id_box.value,
            selected_room,
            start_box.value,
            end_box.value
        )

        step2_card.set_visibility(False)
        step3_card.set_visibility(True)


ui.run(reload=False)