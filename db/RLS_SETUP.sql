-- Enable row-level security on all tables
ALTER TABLE fleets ENABLE ROW LEVEL SECURITY;
ALTER TABLE vehicles ENABLE ROW LEVEL SECURITY;
ALTER TABLE drivers ENABLE ROW LEVEL SECURITY;
ALTER TABLE trips ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_telemetry ENABLE ROW LEVEL SECURITY;
ALTER TABLE processed_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE maintenance_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE geofence_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_daily_summary ENABLE ROW LEVEL SECURITY;
ALTER TABLE driver_trip_map ENABLE ROW LEVEL SECURITY;
ALTER TABLE charging_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE battery_cycles ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;

-- Create fleet_rls policy for each table
CREATE POLICY fleet_rls ON fleets
    USING (fleet_id = current_setting('app.fleet_id', true)::integer);

CREATE POLICY fleet_rls ON vehicles
    USING (fleet_id = current_setting('app.fleet_id', true)::integer);

CREATE POLICY fleet_rls ON drivers
    USING (fleet_id = current_setting('app.fleet_id', true)::integer);

CREATE POLICY fleet_rls ON trips
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

CREATE POLICY fleet_rls ON raw_telemetry
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

CREATE POLICY fleet_rls ON processed_metrics
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

CREATE POLICY fleet_rls ON maintenance_logs
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

CREATE POLICY fleet_rls ON geofence_events
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

CREATE POLICY fleet_rls ON fleet_daily_summary
    USING (fleet_id = current_setting('app.fleet_id', true)::integer);

CREATE POLICY fleet_rls ON driver_trip_map
    USING (driver_id IN (SELECT driver_id FROM drivers WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

CREATE POLICY fleet_rls ON charging_sessions
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

CREATE POLICY fleet_rls ON battery_cycles
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));

CREATE POLICY fleet_rls ON alerts
    USING (vehicle_id IN (SELECT vehicle_id FROM vehicles WHERE fleet_id = current_setting('app.fleet_id', true)::integer));
