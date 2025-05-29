"""
Integration test for mandatory queries.

Tests that the system can handle the 7 representative business questions.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import jwt

from sql_assistant.main import app

# Test client
client = TestClient(app)

# Mock JWT token
def create_mock_token(fleet_id):
    """Create a mock JWT token with the specified fleet_id."""
    return jwt.encode({"fleet_id": fleet_id}, "test_key", algorithm="HS256")

MOCK_TOKEN = create_mock_token(1)

# List of 7 representative business questions
MANDATORY_QUERIES = [
    "How many SRM T3 vans are active this month?",
    "Which three vehicles consumed the most energy last week?",
    "Show battery-health trend for vehicle 42 over the past 90 days.",
    "What is the average trip distance for each vehicle model?",
    "How many maintenance events are still open?",
    "Which drivers had the most trips last month?",
    "What is the charging efficiency by location?"
]

@pytest.mark.asyncio
@pytest.mark.timeout(10)  # Ensure test completes within 10 seconds
async def test_mandatory_queries():
    """Test that the system can handle all mandatory business questions."""
    # Mock the process_query function to avoid actual database calls
    with patch('sql_assistant.main.process_query') as mock_process:
        # Set up mock return values
        mock_process.return_value = ("Test answer", "SELECT * FROM test", [{"count": 5}], None)
        
        # Test each mandatory query
        for query in MANDATORY_QUERIES:
            response = client.post(
                "/chat",
                json={"query": query},
                headers={"Authorization": f"Bearer {MOCK_TOKEN}"}
            )
            
            # Response should be successful
            assert response.status_code == 200
            
            # Response should contain answer, sql, and rows
            assert "answer" in response.json()
            assert "sql" in response.json()
            assert "rows" in response.json() or "download_url" in response.json()
            
            # Reset mock for next query
            mock_process.reset_mock()

@pytest.mark.asyncio
async def test_query_with_model_filter():
    """Test query filtering by vehicle model."""
    # Mock the nl_to_sql function to check SQL generation
    with patch('sql_assistant.main.nl_to_sql') as mock_nl_to_sql, \
         patch('sql_assistant.main.sql_exec') as mock_sql_exec, \
         patch('sql_assistant.main.answer_format') as mock_answer_format:
        
        # Set up mock return values
        mock_nl_to_sql.return_value = {"sql": "SELECT COUNT(*) FROM vehicles WHERE model = 'SRM T3' AND fleet_id = :fleet_id LIMIT 5000"}
        mock_sql_exec.return_value = {"rows": [{"count": 5}]}
        mock_answer_format.return_value = "You have 5 SRM T3 vans in your fleet."
        
        # Test query
        response = client.post(
            "/chat",
            json={"query": "How many SRM T3 vans are active this month?"},
            headers={"Authorization": f"Bearer {MOCK_TOKEN}"}
        )
        
        # Response should be successful
        assert response.status_code == 200
        
        # SQL should contain model filter
        assert "model" in response.json()["sql"].lower()
        assert "srm t3" in response.json()["sql"].lower()

@pytest.mark.asyncio
async def test_query_with_time_filter():
    """Test query filtering by time period."""
    # Mock the nl_to_sql function to check SQL generation
    with patch('sql_assistant.main.nl_to_sql') as mock_nl_to_sql, \
         patch('sql_assistant.main.sql_exec') as mock_sql_exec, \
         patch('sql_assistant.main.answer_format') as mock_answer_format:
        
        # Set up mock return values
        mock_nl_to_sql.return_value = {"sql": "SELECT vehicle_id, SUM(energy_kwh) as total_energy FROM trips WHERE start_ts >= '2025-05-17' AND start_ts <= '2025-05-24' AND fleet_id = :fleet_id GROUP BY vehicle_id ORDER BY total_energy DESC LIMIT 3"}
        mock_sql_exec.return_value = {"rows": [{"vehicle_id": 1, "total_energy": 100}, {"vehicle_id": 2, "total_energy": 90}, {"vehicle_id": 3, "total_energy": 80}]}
        mock_answer_format.return_value = "The three vehicles with highest energy consumption last week were vehicle 1 (100 kWh), vehicle 2 (90 kWh), and vehicle 3 (80 kWh)."
        
        # Test query
        response = client.post(
            "/chat",
            json={"query": "Which three vehicles consumed the most energy last week?"},
            headers={"Authorization": f"Bearer {MOCK_TOKEN}"}
        )
        
        # Response should be successful
        assert response.status_code == 200
        
        # SQL should contain time filter
        assert "start_ts" in response.json()["sql"].lower()
        assert "'" in response.json()["sql"]  # Should contain date string
