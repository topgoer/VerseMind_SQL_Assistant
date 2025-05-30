"""
Test database setup script for CI/CD environments.

This script sets up the test database for integration tests, with 
special handling for CI environments like GitHub Actions.
"""
import os
import sys
import asyncio
import asyncpg
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

async def setup_test_database():
    """Set up the test database for integration tests."""
    
    # Database connection parameters for tests
    db_user = os.environ.get("DB_USER", "postgres")
    db_password = os.environ.get("DB_PASSWORD", "postgres")
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = int(os.environ.get("DB_PORT", "5432"))
    db_name = os.environ.get("DB_NAME", "sql_assistant_test")
    
    # Extract from DATABASE_URL if provided
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        import re
        url_pattern = r"postgresql\+?(?:asyncpg)?://(\w+):(\w+)@([^:]+):(\d+)/(\w+)"
        match = re.match(url_pattern, database_url)
        if match:
            db_user, db_password, db_host, db_port, db_name = match.groups()
            db_port = int(db_port)
    
    print(f"Setting up test database: {db_name} on {db_host}:{db_port}")
    
    try:
        # Connect to the database
        conn = await asyncpg.connect(
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
            database=db_name
        )
        
        # Create minimal test tables for integration tests
        await setup_minimal_schema(conn)
        
        # Insert minimal test data
        await insert_test_data(conn)
        
        await conn.close()
        print("✅ Test database setup completed successfully!")
        
    except Exception as e:
        print(f"❌ Error setting up test database: {e}")
        sys.exit(1)

async def setup_minimal_schema(conn):
    """Create minimal schema required for tests."""
    
    # Create test tables with minimal structure
    tables = {
        "fleets": """
            CREATE TABLE IF NOT EXISTS fleets (
                fleet_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                country TEXT,
                time_zone TEXT
            )
        """,
        "vehicles": """
            CREATE TABLE IF NOT EXISTS vehicles (
                vehicle_id INTEGER PRIMARY KEY,
                vin TEXT,
                fleet_id INTEGER,
                model TEXT,
                make TEXT,
                variant TEXT,
                registration_no TEXT,
                purchase_date DATE,
                FOREIGN KEY (fleet_id) REFERENCES fleets(fleet_id)
            )
        """,
        "drivers": """
            CREATE TABLE IF NOT EXISTS drivers (
                driver_id INTEGER PRIMARY KEY,
                fleet_id INTEGER,
                name TEXT,
                license_no TEXT,
                hire_date DATE,
                FOREIGN KEY (fleet_id) REFERENCES fleets(fleet_id)
            )
        """,
        "trips": """
            CREATE TABLE IF NOT EXISTS trips (
                trip_id INTEGER PRIMARY KEY,
                vehicle_id INTEGER,
                start_ts TIMESTAMP,
                end_ts TIMESTAMP,
                distance_km NUMERIC,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
            )
        """
    }
    
    for table_name, create_sql in tables.items():
        print(f"Creating table: {table_name}")
        await conn.execute(create_sql)

async def insert_test_data(conn):
    """Insert minimal test data for integration tests."""
    
    # Insert test fleet
    await conn.execute("""
        INSERT INTO fleets (fleet_id, name, country, time_zone) 
        VALUES (1, 'Test Fleet', 'USA', 'UTC')
        ON CONFLICT (fleet_id) DO NOTHING
    """)
    
    # Insert test vehicles
    await conn.execute("""
        INSERT INTO vehicles (vehicle_id, vin, fleet_id, model, make, variant, registration_no) 
        VALUES 
            (1, 'VIN001', 1, 'T3', 'SRM', 'Van', 'TEST001'),
            (2, 'VIN002', 1, 'Model Y', 'Tesla', 'Electric', 'TEST002'),
            (3, 'VIN003', 1, 'T3', 'SRM', 'Van', 'TEST003')
        ON CONFLICT (vehicle_id) DO NOTHING
    """)
    
    # Insert test drivers
    await conn.execute("""
        INSERT INTO drivers (driver_id, fleet_id, name, license_no) 
        VALUES 
            (1, 1, 'Test Driver 1', 'DL001'),
            (2, 1, 'Test Driver 2', 'DL002')
        ON CONFLICT (driver_id) DO NOTHING
    """)
    
    # Insert test trips
    await conn.execute("""
        INSERT INTO trips (trip_id, vehicle_id, start_ts, end_ts, distance_km) 
        VALUES 
            (1, 1, '2024-01-01 10:00:00', '2024-01-01 11:00:00', 25.5),
            (2, 2, '2024-01-01 14:00:00', '2024-01-01 15:30:00', 45.2),
            (3, 3, '2024-01-02 09:00:00', '2024-01-02 10:15:00', 18.7)
        ON CONFLICT (trip_id) DO NOTHING
    """)
    
    print("✅ Test data inserted successfully")

if __name__ == "__main__":
    asyncio.run(setup_test_database())
