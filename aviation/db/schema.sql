-- Схема базы данных для хранения стран и воздушных судов.
-- Выполняется командой `python main.py init-db`.

CREATE TABLE IF NOT EXISTS countries (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(128)     NOT NULL UNIQUE,
    iso_code      CHAR(2)          NOT NULL UNIQUE,
    latitude      DOUBLE PRECISION NOT NULL,
    longitude     DOUBLE PRECISION NOT NULL,
    min_latitude  DOUBLE PRECISION NOT NULL,
    max_latitude  DOUBLE PRECISION NOT NULL,
    min_longitude DOUBLE PRECISION NOT NULL,
    max_longitude DOUBLE PRECISION NOT NULL,
    created_at    TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS aeroplanes (
    id              BIGSERIAL PRIMARY KEY,
    icao24          VARCHAR(6)       NOT NULL UNIQUE,
    callsign        VARCHAR(16),
    origin_country  VARCHAR(128),
    time_position   TIMESTAMPTZ,
    last_contact    TIMESTAMPTZ      NOT NULL,
    longitude       DOUBLE PRECISION,
    latitude        DOUBLE PRECISION,
    baro_altitude   DOUBLE PRECISION,
    velocity        DOUBLE PRECISION,
    true_track      DOUBLE PRECISION,
    vertical_rate   DOUBLE PRECISION,
    on_ground       BOOLEAN          NOT NULL DEFAULT FALSE,
    sensors         INTEGER[],
    geo_altitude    DOUBLE PRECISION,
    squawk          VARCHAR(8),
    spi             BOOLEAN          NOT NULL DEFAULT FALSE,
    position_source SMALLINT,
    category        SMALLINT,
    country_id      INTEGER          NOT NULL
        REFERENCES countries (id) ON DELETE CASCADE,
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_aeroplanes_country_id
    ON aeroplanes (country_id);

CREATE INDEX IF NOT EXISTS idx_aeroplanes_velocity
    ON aeroplanes (velocity);

CREATE INDEX IF NOT EXISTS idx_aeroplanes_callsign
    ON aeroplanes (callsign);
