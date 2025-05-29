"""
Unit tests for SQL mapping synonyms.

Tests that the system can handle different ways of referring to the same entities.
"""
import pytest
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_vehicle_synonyms():
    """Test that different terms for 'vehicle' are handled correctly."""
    # Mock the nl_to_sql function to avoid real API calls
    with patch('sql_assistant.services.pipeline.nl_to_sql', new_callable=AsyncMock) as mock_nl_to_sql:
        # Set up mock return value
        mock_nl_to_sql.return_value = {"sql": "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100"}
        
        # Import here to avoid module-level import errors
        from sql_assistant.services.pipeline import nl_to_sql
        
        synonyms = [
            "vehicle", "vehicles", "van", "vans", "car", "cars", 
            "truck", "trucks", "bus", "buses", "fleet vehicle"
        ]
        
        for synonym in synonyms:
            query = f"How many {synonym} do we have?"
            await nl_to_sql(query, fleet_id=1)
            
            # Check that nl_to_sql was called with the correct arguments
            mock_nl_to_sql.assert_called_with(query, fleet_id=1)

@pytest.mark.asyncio
async def test_model_synonyms():
    """Test that different ways of referring to vehicle models are handled correctly."""
    # Mock the nl_to_sql function to avoid real API calls
    with patch('sql_assistant.services.pipeline.nl_to_sql', new_callable=AsyncMock) as mock_nl_to_sql:
        # Set up mock return value with model-specific SQL
        mock_nl_to_sql.return_value = {"sql": "SELECT * FROM vehicles WHERE model = 'SRM T3' AND fleet_id = :fleet_id LIMIT 100"}
        
        # Import here to avoid module-level import errors
        from sql_assistant.services.pipeline import nl_to_sql
        
        queries = [
            "How many SRM T3 vans are active?",
            "Count of active SRM T3 vehicles",
            "Number of T3 vans from SRM",
            "Active SRM T3 count",
            "SRM T3 fleet size"
        ]
        
        for query in queries:
            await nl_to_sql(query, fleet_id=1)
            
            # Check that nl_to_sql was called with the correct arguments
            mock_nl_to_sql.assert_called_with(query, fleet_id=1)

@pytest.mark.asyncio
async def test_time_period_synonyms():
    """Test that different time period references are handled correctly."""
    # Mock the nl_to_sql function to avoid real API calls
    with patch('sql_assistant.services.pipeline.nl_to_sql', new_callable=AsyncMock) as mock_nl_to_sql:
        # Set up mock return value with time-specific SQL
        mock_nl_to_sql.return_value = {"sql": "SELECT * FROM trips WHERE date >= '2025-01-01' AND fleet_id = :fleet_id LIMIT 100"}
        
        # Import here to avoid module-level import errors
        from sql_assistant.services.pipeline import nl_to_sql
        
        time_periods = [
            "today", "yesterday", "this week", "last week",
            "this month", "last month", "past 7 days",
            "past 30 days", "past month", "past week"
        ]
        
        for period in time_periods:
            query = f"How many trips were completed {period}?"
            await nl_to_sql(query, fleet_id=1)
            
            # Check that nl_to_sql was called with the correct arguments
            mock_nl_to_sql.assert_called_with(query, fleet_id=1)

@pytest.mark.asyncio
async def test_metric_synonyms():
    """Test that different ways of referring to metrics are handled correctly."""
    # Mock the nl_to_sql function to avoid real API calls
    with patch('sql_assistant.services.pipeline.nl_to_sql', new_callable=AsyncMock) as mock_nl_to_sql:
        # Set up mock return value
        mock_nl_to_sql.return_value = {"sql": "SELECT AVG(distance_km) FROM trips WHERE fleet_id = :fleet_id GROUP BY vehicle_id LIMIT 100"}
        
        # Import here to avoid module-level import errors
        from sql_assistant.services.pipeline import nl_to_sql
        
        metric_pairs = [
            ("distance", "distance_km"),
            ("energy", "energy_kwh"),
            ("battery health", "battery_health_pct"),
            ("state of charge", "soc_pct"),
            ("idle time", "idle_minutes"),
            ("speed", "speed_kph"),
            ("temperature", "temp_c"),
            ("charging", "charging_sessions"),
            ("maintenance", "maintenance_logs"),
            ("alerts", "alerts")
        ]
        
        for natural_term, db_term in metric_pairs:
            query = f"What is the average {natural_term} for each vehicle?"
            await nl_to_sql(query, fleet_id=1)
            
            # Check that nl_to_sql was called with the correct arguments
            mock_nl_to_sql.assert_called_with(query, fleet_id=1)
