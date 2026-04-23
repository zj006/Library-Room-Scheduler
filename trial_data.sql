INSERT INTO role VALUES
(1, 'student'),
(2, 'admin');

INSERT INTO useraccount VALUES
(1, 'Zach Johns', 'zach@email.com', 1),
(2, 'Emily Carter', 'emily@email.com', 1),
(3, 'Marcus Lee', 'marcus@email.com', 1),
(4, 'Library Admin', 'admin@email.com', 2);

INSERT INTO building VALUES
(1, 'Main Library', 'Campus Center', '8am-10pm'),
(2, 'Science Building', 'North Campus', '7am-9pm');

INSERT INTO room VALUES
(1, 1, 'Study Room A', 4, false, 120, 'Small study room'),
(2, 1, 'Study Room B', 8, false, 180, 'Medium group room'),
(3, 1, 'Quiet Room', 2, false, 90, 'Individual quiet room'),
(4, 2, 'Group Room 1', 10, true, 180, 'Large group room'),
(5, 2, 'Conference Room', 15, true, 240, 'Conference-style room');

INSERT INTO feature VALUES
(1, 'Projector'),
(2, 'Whiteboard'),
(3, 'Computer'),
(4, 'TV Screen');

INSERT INTO room_feature VALUES
(1, 2),
(2, 1),
(2, 2),
(3, 2),
(4, 1),
(4, 2),
(4, 3),
(5, 1),
(5, 4);

INSERT INTO reservation VALUES
(1, 1, 1, '2026-04-10 10:00:00', '2026-04-10 11:00:00', 'Study group', 3, 'approved'),
(2, 2, 2, '2026-04-10 12:00:00', '2026-04-10 13:00:00', 'Group project', 5, 'pending'),
(3, 3, 4, '2026-04-11 14:00:00', '2026-04-11 15:30:00', 'Club meeting', 8, 'approved'),
(4, 1, 5, '2026-04-12 09:00:00', '2026-04-12 10:30:00', 'Presentation practice', 12, 'rejected');

INSERT INTO approval VALUES
(1, 3, 4, 'approved', '2026-04-10 09:30:00', 'Approved for club meeting'),
(2, 4, 4, 'rejected', '2026-04-10 09:45:00', 'Room unavailable for that setup');

INSERT INTO room_block VALUES
(1, 3, '2026-04-13 08:00:00', '2026-04-13 10:00:00', 'Cleaning'),
(2, 5, '2026-04-14 12:00:00', '2026-04-14 15:00:00', 'Maintenance');