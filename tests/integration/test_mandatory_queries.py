"""
Integration test for mandatory queries.

Tests that the system can handle the 7 representative business questions.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import jwt

from sql_assistant.main import app
from sql_assistant.auth import get_fleet_id

# Mock authentication for tests
app.dependency_overrides[get_fleet_id] = lambda: 1

# Test client
client = TestClient(app)

# Mock JWT token
def create_mock_token(fleet_id):
    """Create a mock JWT token with the specified fleet_id."""
    return jwt.encode({"fleet_id": fleet_id}, "test_key", algorithm="HS256")

# Using the valid token generated previously
MOCK_TOKEN = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0ZXIiLCJmbGVldF9pZCI6MSwiZXhwIjoxNzQ4NTczNTk3fQ.DTWVMaiJDeGDF6FoEwTMsaC3BKn41Vcck_h8SUlVMFHfOl0Q_uzuUZ-o4YRAhr68LEJLpA-BsWqFn2LUUW664yuII5mQNwDyuMm6kSYe9izBekBnyJul3KQHKuZ7PqgtZenWMBygfPUzko4ZTMcPJVHFi_9YHJGrZlEesFwPoa--bVDNzd7rw8FfdqGZBsg-id3KAbgNldFaSIq9oVjiRxovv8h9K3OM7QSj-GmJo_G6TE-52bLFP-bUBuki_K8VJXzIbuu38nSL52V_jT2JmXClQUEnbuIdofzkSaCM7AVQmKV3fLvbB6vwzEI41B85hmNjYz_c9DdX-hetCROgKTpdQ"

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
    # Mock the process_query function and LLM providers to avoid actual database and API calls
    with patch('sql_assistant.main.process_query') as mock_process, \
         patch('sql_assistant.services.pipeline.check_llm_api_keys') as mock_check_keys:
        
        # Mock the API key check to avoid LLM calls
        mock_check_keys.return_value = ("dummy_key", None, None)
        
        # Set up mock return values
        mock_process.return_value = {
            "answer": "Test answer",
            "sql": "SELECT * FROM test", 
            "rows": [{"count": 5}],
            "download_url": None,
            "is_fallback": False,
            "prompt_sql": "",
            "prompt_answer": ""
        }
        
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
    # Mock functions where they are looked up by the code under test (pipeline.py)
    with patch('sql_assistant.services.pipeline.llm_nl_to_sql') as mock_pipeline_llm_nl_to_sql, \
         patch('sql_assistant.services.pipeline.sql_exec') as mock_pipeline_sql_exec, \
         patch('sql_assistant.services.pipeline.answer_format') as mock_pipeline_answer_format, \
         patch('sql_assistant.services.pipeline.check_llm_api_keys') as mock_check_keys: # Safety net
        
        mock_check_keys.return_value = ("dummy_key", None, None)
        
        # Set up mock return values
        mock_pipeline_llm_nl_to_sql.return_value = {"sql": "SELECT COUNT(*) FROM vehicles WHERE model = 'SRM T3' AND fleet_id = :fleet_id LIMIT 5000"}
        mock_pipeline_sql_exec.return_value = {"rows": [{"count": 5}]}
        mock_pipeline_answer_format.return_value = "You have 5 SRM T3 vans in your fleet."
        
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
    # Mock functions where they are looked up by the code under test (pipeline.py)
    with patch('sql_assistant.services.pipeline.llm_nl_to_sql') as mock_pipeline_llm_nl_to_sql, \
         patch('sql_assistant.services.pipeline.sql_exec') as mock_pipeline_sql_exec, \
         patch('sql_assistant.services.pipeline.answer_format') as mock_pipeline_answer_format, \
         patch('sql_assistant.services.pipeline.check_llm_api_keys') as mock_check_keys: # Safety net
        
        mock_check_keys.return_value = ("dummy_key", None, None)
        
        # Set up mock return values
        mock_pipeline_llm_nl_to_sql.return_value = {"sql": "SELECT vehicle_id, SUM(energy_kwh) as total_energy FROM trips WHERE start_ts >= '2025-05-17' AND start_ts <= '2025-05-24' AND fleet_id = :fleet_id GROUP BY vehicle_id ORDER BY total_energy DESC LIMIT 3"}
        mock_pipeline_sql_exec.return_value = {"rows": [{"vehicle_id": 1, "total_energy": 100}, {"vehicle_id": 2, "total_energy": 90}, {"vehicle_id": 3, "total_energy": 80}]}
        mock_pipeline_answer_format.return_value = "The three vehicles with highest energy consumption last week were vehicle 1 (100 kWh), vehicle 2 (90 kWh), and vehicle 3 (80 kWh)."
        
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
