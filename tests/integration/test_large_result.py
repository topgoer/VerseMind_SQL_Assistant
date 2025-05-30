"""
Integration test for large result path.

Tests that queries returning >100 rows provide a download_url and create the file.
"""
import pytest
import os
import uuid
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

@pytest.mark.asyncio
@pytest.mark.timeout(10)  # Ensure test completes within 10 seconds
async def test_large_result_path():
    """Test that queries returning >100 rows provide a download_url and create the file."""
    # Mock the process_query function directly to avoid DB access issues and LLM providers
    with patch('sql_assistant.main.process_query') as mock_process, \
         patch('sql_assistant.services.pipeline.check_llm_api_keys') as mock_check_keys:
        
        # Mock the API key check to avoid LLM calls
        mock_check_keys.return_value = ("dummy_key", None, None)
        
        # Generate a unique filename for testing
        test_filename = f"{uuid.uuid4()}.csv"
        test_filepath = os.path.join("static", test_filename)
        
        # Set up mock return values for process_query
        mock_process.return_value = (
            "Found 150 telemetry records.",
            "SELECT * FROM raw_telemetry LIMIT 5000",
            None,  # No rows for large result
            f"/static/{test_filename}", 
            False  # Not fallback
        )
        
        # Create an empty file to simulate the CSV being written
        os.makedirs("static", exist_ok=True)
        with open(test_filepath, "w") as f:
            f.write("header1,header2\n")
            for i in range(150):
                f.write(f"value{i},value{i}\n")
        
        try:
            # Test /chat endpoint
            response = client.post(
                "/chat",
                json={"query": "Show all telemetry data"},
                headers={"Authorization": f"Bearer {MOCK_TOKEN}"}
            )
            
            # Response should be successful
            assert response.status_code == 200
            
            # Response should contain download_url but not rows
            assert "download_url" in response.json()
            assert response.json()["download_url"] == f"/static/{test_filename}"
            assert "rows" not in response.json() or response.json()["rows"] is None
            
            # File should exist
            assert os.path.exists(test_filepath)
            
            # Test file content
            with open(test_filepath, "r") as f:
                content = f.read()
                assert "header1,header2" in content
                assert "value0,value0" in content
                assert "value149,value149" in content
        
        finally:
            # Clean up test file
            if os.path.exists(test_filepath):
                os.remove(test_filepath)

@pytest.mark.asyncio
@pytest.mark.timeout(10)  # Ensure test completes within 10 seconds
async def test_small_result_path():
    """Test that queries returning ≤100 rows provide rows directly and not download_url."""
    # Mock the process_query function to return a small result set and LLM providers
    with patch('sql_assistant.main.process_query') as mock_process, \
         patch('sql_assistant.services.pipeline.check_llm_api_keys') as mock_check_keys:
        
        # Mock the API key check to avoid LLM calls
        mock_check_keys.return_value = ("dummy_key", None, None)
        
        # Set up mock return values for a small result set
        mock_rows = [{"id": i, "value": f"test{i}"} for i in range(10)]
        mock_process.return_value = ("Test answer", "SELECT * FROM test LIMIT 10", mock_rows, None, False)
        
        # Test /chat endpoint
        response = client.post(
            "/chat",
            json={"query": "Show 10 vehicles"},
            headers={"Authorization": f"Bearer {MOCK_TOKEN}"}
        )
        
        # Response should be successful
        assert response.status_code == 200
        
        # Response should contain rows but not download_url
        assert "rows" in response.json()
        assert len(response.json()["rows"]) == 10
        assert "download_url" not in response.json() or response.json()["download_url"] is None
