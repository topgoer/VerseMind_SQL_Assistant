import os
import pandas as pd
import yaml

UPLOAD_DIR = 'upload'
SCHEMA_PATH = 'sql_assistant/services/database_schema.yaml'

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

def infer_type(series):
    if pd.api.types.is_integer_dtype(series):
        return 'integer'
    elif pd.api.types.is_float_dtype(series):
        return 'numeric'
    elif pd.api.types.is_bool_dtype(series):
        return 'boolean'
    elif pd.api.types.is_datetime64_any_dtype(series):
        return 'timestamp'
    else:
        return 'varchar'

def generate_database_schema():
    schema = {'tables': {}, 'critical_info': []}
    for fname in CSV_FILES:
        path = os.path.join(UPLOAD_DIR, fname)
        if os.path.exists(path):
            table = fname[:-4]
            df = pd.read_csv(path, nrows=100)
            columns = {}
            for col in df.columns:
                col_type = infer_type(df[col])
                example = df[col].dropna().iloc[0] if not df[col].dropna().empty else ''
                columns[col] = {'type': col_type, 'example': str(example)}
            schema['tables'][table] = {'columns': columns}
    with open(SCHEMA_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(schema, f, allow_unicode=True, sort_keys=False)
    print(f"database_schema.yaml generated at {SCHEMA_PATH}")

if __name__ == "__main__":
    generate_database_schema() 