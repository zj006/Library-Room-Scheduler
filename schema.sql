DROP TABLE IF EXISTS approval;
DROP TABLE IF EXISTS room_feature;
DROP TABLE IF EXISTS reservation;
DROP TABLE IF EXISTS room_block;
DROP TABLE IF EXISTS feature;
DROP TABLE IF EXISTS room;
DROP TABLE IF EXISTS building;
DROP TABLE IF EXISTS useraccount;
DROP TABLE IF EXISTS role;

CREATE TABLE role (
    role_id INT PRIMARY KEY,
    role_name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE useraccount (
    user_id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    role_id INT NOT NULL,
    FOREIGN KEY (role_id) REFERENCES role(role_id)
);

CREATE TABLE building (
    building_id INT PRIMARY KEY,
    building_name VARCHAR(100) NOT NULL,
    address VARCHAR(200),
    hours VARCHAR(100)
);

CREATE TABLE room (
    room_id INT PRIMARY KEY,
    building_id INT NOT NULL,
    room_name VARCHAR(100) NOT NULL,
    capacity INT NOT NULL CHECK (capacity > 0),
    approval_required BOOLEAN NOT NULL DEFAULT FALSE,
    max_duration_minutes INT CHECK (max_duration_minutes > 0),
    dimensions VARCHAR(100),
    FOREIGN KEY (building_id) REFERENCES building(building_id)
);

CREATE TABLE feature (
    feature_id INT PRIMARY KEY,
    feature_name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE room_feature (
    room_id INT,
    feature_id INT,
    PRIMARY KEY (room_id, feature_id),
    FOREIGN KEY (room_id) REFERENCES room(room_id),
    FOREIGN KEY (feature_id) REFERENCES feature(feature_id)
);

CREATE TABLE reservation (
    reservation_id INT PRIMARY KEY,
    user_id INT NOT NULL,
    room_id INT NOT NULL,
    start_datetime TIMESTAMP NOT NULL,
    end_datetime TIMESTAMP NOT NULL,
    purpose VARCHAR(200),
    attendee_count INT NOT NULL CHECK (attendee_count >= 0),
    status VARCHAR(50) NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    FOREIGN KEY (user_id) REFERENCES useraccount(user_id),
    FOREIGN KEY (room_id) REFERENCES room(room_id),
    CHECK (end_datetime > start_datetime)
);

CREATE TABLE approval (
    approval_id INT PRIMARY KEY,
    reservation_id INT UNIQUE NOT NULL,
    admin_id INT NOT NULL,
    decision VARCHAR(50) NOT NULL CHECK (decision IN ('approved', 'rejected')),
    decision_time TIMESTAMP NOT NULL,
    notes VARCHAR(300),
    FOREIGN KEY (reservation_id) REFERENCES reservation(reservation_id),
    FOREIGN KEY (admin_id) REFERENCES useraccount(user_id)
);

CREATE TABLE room_block (
    block_id INT PRIMARY KEY,
    room_id INT NOT NULL,
    start_datetime TIMESTAMP NOT NULL,
    end_datetime TIMESTAMP NOT NULL,
    reason VARCHAR(200) NOT NULL,
    FOREIGN KEY (room_id) REFERENCES room(room_id),
    CHECK (end_datetime > start_datetime)
);

-- Indexes for performance
-- Speeds up availability checks (most frequent query)
CREATE INDEX IF NOT EXISTS idx_reservation_room_id
    ON reservation(room_id);

-- Speeds up filtering by status (approved/pending/rejected)
CREATE INDEX IF NOT EXISTS idx_reservation_status
    ON reservation(status);

-- Speeds up login lookup by email
CREATE INDEX IF NOT EXISTS idx_useraccount_email
    ON useraccount(email);

-- Speeds up admin panel query for pending reservations
CREATE INDEX IF NOT EXISTS idx_reservation_status_start
    ON reservation(status, start_datetime);

-- Speeds up room block availability checks
CREATE INDEX IF NOT EXISTS idx_room_block_room_id
    ON room_block(room_id);