"""
Database import script for VerseMind SQL Assistant.

This script imports CSV data into PostgreSQL tables, creates indexes,
and sets up Row-Level Security (RLS) policies.

Database connection can be configured using environment variables:
- DATABASE_URL: Full PostgreSQL connection string (if provided, other DB_* variables are ignored)
- DB_USER: Database username (default: postgres)
- DB_PASSWORD: Database password (required for security)
- DB_HOST: Database host (default: db)
- DB_PORT: Database port (default: 5432)
- DB_NAME: Database name (default: sql_assistant)
"""
import os
import sys
import asyncio
import asyncpg
from datetime import datetime
import io

# Try to import dotenv, install it if it's not available
try:
    from dotenv import load_dotenv
    # Load environment variables
    load_dotenv()
except ImportError:
    print("Warning: python-dotenv not found, continuing without loading .env file")

print("Loaded DATABASE_URL:", os.environ.get("DATABASE_URL"))

# CSV file paths
# Check if running in Docker container
if os.path.exists('/home/ubuntu/upload'):
    CSV_DIR = "/home/ubuntu/upload"
else:
    CSV_DIR = "upload"
CSV_FILES = [
    "fleets.csv",
    "vehicles.csv",
    "drivers.csv",
    "trips.csv",
    "raw_telemetry.csv",
    "processed_metrics.csv",
    "maintenance_logs.csv",
    "geofence_events.csv",
    "fleet_daily_summary.csv",
    "driver_trip_map.csv",
    "charging_sessions.csv",
    "battery_cycles.csv",
    "alerts.csv"
]

# Table definitions with proper data types
TABLE_DEFINITIONS = {
    "fleets": """
        CREATE TABLE fleets (
            fleet_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            country TEXT NOT NULL,
            time_zone TEXT NOT NULL
        )
    """,
    "vehicles": """
        CREATE TABLE vehicles (
            vehicle_id INTEGER PRIMARY KEY,
            vin TEXT NOT NULL,
            fleet_id INTEGER NOT NULL REFERENCES fleets(fleet_id),
            model TEXT NOT NULL,
            make TEXT NOT NULL,
            variant TEXT NOT NULL,
            registration_no TEXT NOT NULL,
            purchase_date DATE NOT NULL
        )
    """,
    "drivers": """
        CREATE TABLE drivers (
            driver_id INTEGER PRIMARY KEY,
            fleet_id INTEGER NOT NULL REFERENCES fleets(fleet_id),
            name TEXT NOT NULL,
            license_no TEXT NOT NULL,
            hire_date DATE NOT NULL
        )
    """,
    "trips": """
        CREATE TABLE trips (
            trip_id INTEGER PRIMARY KEY,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
            start_ts TIMESTAMP NOT NULL,
            end_ts TIMESTAMP NOT NULL,
            distance_km NUMERIC NOT NULL,
            energy_kwh NUMERIC NOT NULL,
            idle_minutes NUMERIC NOT NULL,
            avg_temp_c NUMERIC NOT NULL
        )
    """,
    "raw_telemetry": """
        CREATE TABLE raw_telemetry (
            ts TIMESTAMP NOT NULL,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
            soc_pct NUMERIC NOT NULL,
            pack_voltage_v NUMERIC NOT NULL,
            pack_current_a NUMERIC NOT NULL,
            batt_temp_c NUMERIC NOT NULL,
            latitude NUMERIC NOT NULL,
            longitude NUMERIC NOT NULL,
            speed_kph NUMERIC NOT NULL,
            odo_km NUMERIC NOT NULL,
            PRIMARY KEY (ts, vehicle_id)
        )
    """,
    "processed_metrics": """
        CREATE TABLE processed_metrics (
            ts TIMESTAMP NOT NULL,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
            avg_speed_kph_15m NUMERIC NOT NULL,
            distance_km_15m NUMERIC NOT NULL,
            energy_kwh_15m NUMERIC NOT NULL,
            battery_health_pct NUMERIC NOT NULL,
            soc_band TEXT NOT NULL,
            PRIMARY KEY (ts, vehicle_id)
        )
    """,
    "maintenance_logs": """
        CREATE TABLE maintenance_logs (
            maint_id INTEGER PRIMARY KEY,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
            maint_type TEXT NOT NULL,
            start_ts TIMESTAMP NOT NULL,
            end_ts TIMESTAMP NOT NULL,
            cost_sgd NUMERIC NOT NULL,
            notes TEXT
        )
    """,
    "geofence_events": """
        CREATE TABLE geofence_events (
            event_id INTEGER PRIMARY KEY,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
            geofence_name TEXT NOT NULL,
            enter_ts TIMESTAMP NOT NULL,
            exit_ts TIMESTAMP NOT NULL
        )
    """,
    "fleet_daily_summary": """
        CREATE TABLE fleet_daily_summary (
            fleet_id INTEGER NOT NULL REFERENCES fleets(fleet_id),
            date DATE NOT NULL,
            total_distance_km NUMERIC NOT NULL,
            total_energy_kwh NUMERIC NOT NULL,
            active_vehicles INTEGER NOT NULL,
            avg_soc_pct NUMERIC NOT NULL,
            PRIMARY KEY (fleet_id, date)
        )
    """,
    "driver_trip_map": """
        CREATE TABLE driver_trip_map (
            trip_id INTEGER NOT NULL REFERENCES trips(trip_id),
            driver_id INTEGER NOT NULL REFERENCES drivers(driver_id),
            primary_bool BOOLEAN NOT NULL,
            PRIMARY KEY (trip_id, driver_id)
        )
    """,
    "charging_sessions": """
        CREATE TABLE charging_sessions (
            session_id INTEGER PRIMARY KEY,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
            start_ts TIMESTAMP NOT NULL,
            end_ts TIMESTAMP NOT NULL,
            start_soc NUMERIC NOT NULL,
            end_soc NUMERIC NOT NULL,
            energy_kwh NUMERIC NOT NULL,
            location TEXT NOT NULL
        )
    """,
    "battery_cycles": """
        CREATE TABLE battery_cycles (
            cycle_id INTEGER PRIMARY KEY,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
            ts TIMESTAMP NOT NULL,
            dod_pct NUMERIC NOT NULL,
            soh_pct NUMERIC NOT NULL
        )
    """,
    "alerts": """
        CREATE TABLE alerts (
            alert_id INTEGER PRIMARY KEY,
            vehicle_id INTEGER NOT NULL REFERENCES vehicles(vehicle_id),
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            alert_ts TIMESTAMP NOT NULL,
            value NUMERIC NOT NULL,
            threshold NUMERIC NOT NULL,
            resolved_bool BOOLEAN NOT NULL,
            resolved_ts TIMESTAMP
        )
    """
}

# Indexes for performance
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_vehicles_fleet_id ON vehicles(fleet_id)",
    "CREATE INDEX IF NOT EXISTS idx_trips_vehicle_id ON trips(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_trips_start_ts ON trips(start_ts)",
    "CREATE INDEX IF NOT EXISTS idx_raw_telemetry_vehicle_id_ts ON raw_telemetry(vehicle_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_processed_metrics_vehicle_id_ts ON processed_metrics(vehicle_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_maintenance_logs_vehicle_id ON maintenance_logs(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_geofence_events_vehicle_id ON geofence_events(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_charging_sessions_vehicle_id ON charging_sessions(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_battery_cycles_vehicle_id ON battery_cycles(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_vehicle_id ON alerts(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_drivers_fleet_id ON drivers(fleet_id)"
]

# RLS setup
RLS_SETUP = """
ALTER TABLE fleets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON fleets;
CREATE POLICY fleet_rls ON fleets
    USING (fleet_id = current_setting('app.fleet_id', true)::integer);

ALTER TABLE vehicles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON vehicles;
CREATE POLICY fleet_rls ON vehicles
    USING (fleet_id = current_setting('app.fleet_id', true)::integer);

ALTER TABLE drivers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON drivers;
CREATE POLICY fleet_rls ON drivers
    USING (fleet_id = current_setting('app.fleet_id', true)::integer);

ALTER TABLE trips ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON trips;
CREATE POLICY fleet_rls ON trips
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

ALTER TABLE raw_telemetry ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON raw_telemetry;
CREATE POLICY fleet_rls ON raw_telemetry
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

ALTER TABLE processed_metrics ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON processed_metrics;
CREATE POLICY fleet_rls ON processed_metrics
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

ALTER TABLE maintenance_logs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON maintenance_logs;
CREATE POLICY fleet_rls ON maintenance_logs
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

ALTER TABLE geofence_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON geofence_events;
CREATE POLICY fleet_rls ON geofence_events
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

ALTER TABLE fleet_daily_summary ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON fleet_daily_summary;
CREATE POLICY fleet_rls ON fleet_daily_summary
    USING (fleet_id = current_setting('app.fleet_id', true)::integer);

ALTER TABLE driver_trip_map ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON driver_trip_map;
CREATE POLICY fleet_rls ON driver_trip_map
    USING (driver_id IN (SELECT driver_id FROM drivers WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

ALTER TABLE charging_sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON charging_sessions;
CREATE POLICY fleet_rls ON charging_sessions
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

ALTER TABLE battery_cycles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON battery_cycles;
CREATE POLICY fleet_rls ON battery_cycles
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fleet_rls ON alerts;
CREATE POLICY fleet_rls ON alerts
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));
"""

# Vector extension setup
VECTOR_SETUP = """
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        CREATE EXTENSION IF NOT EXISTS vector;
    END IF;
EXCEPTION
    WHEN undefined_file THEN
        RAISE NOTICE 'pgvector extension not available, skipping...';
END $$;
"""

# Column type mapping for each table
COLUMN_TYPE_MAP = {
    "fleets": [
        ("fleet_id", "INTEGER"),
        ("name", "TEXT"),
        ("country", "TEXT"),
        ("time_zone", "TEXT"),
    ],
    "vehicles": [
        ("vehicle_id", "INTEGER"),
        ("vin", "TEXT"),
        ("fleet_id", "INTEGER"),
        ("model", "TEXT"),
        ("make", "TEXT"),
        ("variant", "TEXT"),
        ("registration_no", "TEXT"),
        ("purchase_date", "DATE"),
    ],
    "drivers": [
        ("driver_id", "INTEGER"),
        ("fleet_id", "INTEGER"),
        ("name", "TEXT"),
        ("license_no", "TEXT"),
        ("hire_date", "DATE"),
    ],
    "trips": [
        ("trip_id", "INTEGER"),
        ("vehicle_id", "INTEGER"),
        ("start_ts", "TIMESTAMP"),
        ("end_ts", "TIMESTAMP"),
        ("distance_km", "NUMERIC"),
        ("energy_kwh", "NUMERIC"),
        ("idle_minutes", "NUMERIC"),
        ("avg_temp_c", "NUMERIC"),
    ],
    "raw_telemetry": [
        ("ts", "TIMESTAMP"),
        ("vehicle_id", "INTEGER"),
        ("soc_pct", "NUMERIC"),
        ("pack_voltage_v", "NUMERIC"),
        ("pack_current_a", "NUMERIC"),
        ("batt_temp_c", "NUMERIC"),
        ("latitude", "NUMERIC"),
        ("longitude", "NUMERIC"),
        ("speed_kph", "NUMERIC"),
        ("odo_km", "NUMERIC"),
    ],
    "processed_metrics": [
        ("ts", "TIMESTAMP"),
        ("vehicle_id", "INTEGER"),
        ("avg_speed_kph_15m", "NUMERIC"),
        ("distance_km_15m", "NUMERIC"),
        ("energy_kwh_15m", "NUMERIC"),
        ("battery_health_pct", "NUMERIC"),
        ("soc_band", "TEXT"),
    ],
    "maintenance_logs": [
        ("maint_id", "INTEGER"),
        ("vehicle_id", "INTEGER"),
        ("maint_type", "TEXT"),
        ("start_ts", "TIMESTAMP"),
        ("end_ts", "TIMESTAMP"),
        ("cost_sgd", "NUMERIC"),
        ("notes", "TEXT"),
    ],
    "geofence_events": [
        ("event_id", "INTEGER"),
        ("vehicle_id", "INTEGER"),
        ("geofence_name", "TEXT"),
        ("enter_ts", "TIMESTAMP"),
        ("exit_ts", "TIMESTAMP"),
    ],
    "fleet_daily_summary": [
        ("fleet_id", "INTEGER"),
        ("date", "DATE"),
        ("total_distance_km", "NUMERIC"),
        ("total_energy_kwh", "NUMERIC"),
        ("active_vehicles", "INTEGER"),
        ("avg_soc_pct", "NUMERIC"),
    ],
    "driver_trip_map": [
        ("trip_id", "INTEGER"),
        ("driver_id", "INTEGER"),
        ("primary_bool", "BOOLEAN"),
    ],
    "charging_sessions": [
        ("session_id", "INTEGER"),
        ("vehicle_id", "INTEGER"),
        ("start_ts", "TIMESTAMP"),
        ("end_ts", "TIMESTAMP"),
        ("start_soc", "NUMERIC"),
        ("end_soc", "NUMERIC"),
        ("energy_kwh", "NUMERIC"),
        ("location", "TEXT"),
    ],
    "battery_cycles": [
        ("cycle_id", "INTEGER"),
        ("vehicle_id", "INTEGER"),
        ("ts", "TIMESTAMP"),
        ("dod_pct", "NUMERIC"),
        ("soh_pct", "NUMERIC"),
    ],
    "alerts": [
        ("alert_id", "INTEGER"),
        ("vehicle_id", "INTEGER"),
        ("alert_type", "TEXT"),
        ("severity", "TEXT"),
        ("alert_ts", "TIMESTAMP"),
        ("value", "NUMERIC"),
        ("threshold", "NUMERIC"),
        ("resolved_bool", "BOOLEAN"),
        ("resolved_ts", "TIMESTAMP"),
    ],
}

async def import_csv_to_table(conn, table_name, csv_path):
    print(f"Importing {csv_path} into {table_name}...")

    with open(csv_path, 'r', encoding='utf-8') as f:
        header = f.readline().strip()
        columns = header.split(',')
        column_defs = ', '.join([f'"{col}" TEXT' for col in columns])
        temp_table = f"temp_{table_name}"
        await conn.execute(f"CREATE TEMPORARY TABLE {temp_table} ({column_defs})")

        # Read the rest of the file (data rows)
        data = f.read()
        data_bytes = data.encode('utf-8')
        data_stream = io.BytesIO(data_bytes)
        await conn.copy_to_table(temp_table, source=data_stream, format='csv')

        # Build casted select for insert
        type_map = COLUMN_TYPE_MAP[table_name]
        casted_columns = ', '.join([
            f'"{col}"::{col_type}' for col, col_type in type_map
        ])
        column_list = ', '.join([f'"{col}"' for col, _ in type_map])
        await conn.execute(
            f"INSERT INTO {table_name} ({column_list}) SELECT {casted_columns} FROM {temp_table}"
        )
        await conn.execute(f"DROP TABLE {temp_table}")

    row_count = await conn.fetchval(f"SELECT COUNT(*) FROM {table_name}")
    print(f"Imported {row_count} rows into {table_name}")

async def get_database_url():
    """Get the database connection URL from environment variables."""
    db_user = os.environ.get("DB_USER", "postgres")
    db_password = os.environ.get("DB_PASSWORD", "")
    db_host = os.environ.get("DB_HOST", "db")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "sql_assistant")
    
    # Use DATABASE_URL if provided, otherwise build from individual parameters
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        database_url = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    
    # Log the URL (with password masked for security)
    masked_url = database_url.replace(db_password, '********') if db_password else database_url
    print(f"Connecting to database: {masked_url}")
    return database_url

async def get_existing_tables(conn):
    """Get a list of existing tables in the database."""
    existing_tables = []
    result = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    for row in result:
        existing_tables.append(row['tablename'])
    return existing_tables

async def truncate_tables(conn, truncate_order, existing_tables):
    """Truncate existing tables in the correct order."""
    print("Truncating existing tables...")
    for table in truncate_order:
        if table in existing_tables:
            try:
                await conn.execute(f'TRUNCATE TABLE {table} CASCADE')
                print(f'Truncated {table}')
            except Exception as e:
                print(f'Error: Failed to truncate {table}: {e}')
        # Skip tables that don't exist without any messages or warnings

async def create_tables(conn):
    """Create database tables if they don't exist."""
    for table_name, create_stmt in TABLE_DEFINITIONS.items():
        print(f"Creating table: {table_name}")
        try:
            await conn.execute(create_stmt)
        except asyncpg.exceptions.DuplicateTableError:
            print(f"Table {table_name} already exists, skipping creation")

async def import_data(conn):
    """Import CSV data into tables."""
    for csv_file in CSV_FILES:
        table_name = os.path.splitext(csv_file)[0]
        csv_path = os.path.join(CSV_DIR, csv_file)
        
        if os.path.exists(csv_path):
            await import_csv_to_table(conn, table_name, csv_path)
        else:
            print(f"Warning: CSV file not found: {csv_path}")

async def create_db_indexes(conn):
    """Create database indexes for performance."""
    print("Creating indexes...")
    for index_stmt in INDEXES:
        try:
            await conn.execute(index_stmt)
        except asyncpg.exceptions.DuplicateObjectError:
            print(f"Index already exists, skipping: {index_stmt}")

async def setup_row_level_security(conn):
    """Set up Row-Level Security policies."""
    print("Setting up Row-Level Security...")
    await conn.execute(RLS_SETUP)

async def main():
    """Main function to set up the database."""
    database_url = await get_database_url()
    # Fix DSN for asyncpg: replace 'postgresql+asyncpg://' with 'postgresql://'
    database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(database_url)
    
    try:
        # Define the order for truncating tables (to avoid FK constraints)
        truncate_order = [
            "driver_trip_map", "charging_sessions", "battery_cycles", 
            "alerts", "processed_metrics", "raw_telemetry", 
            "trips", "maintenance_logs", "geofence_events", 
            "fleet_daily_summary", "drivers", "vehicles", "fleets"
        ]
        
        # Get existing tables
        existing_tables = await get_existing_tables(conn)
        
        # Execute database setup steps
        await truncate_tables(conn, truncate_order, existing_tables)
        await create_tables(conn)
        await import_data(conn)
        await create_db_indexes(conn)
        await setup_row_level_security(conn)
        
        print("Database setup completed successfully!")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
