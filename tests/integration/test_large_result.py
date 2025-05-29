"""
Integration test for large result path.

Tests that queries returning >100 rows provide a download_url and create the file.
"""
import pytest
import asyncio
import os
import uuid
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import jwt

from sql_assistant.main import app

# Test client
client = TestClient(app)

# Mock JWT token
def create_mock_token(fleet_id):
    """Create a mock JWT token with the specified fleet_id."""
    return jwt.encode({"fleet_id": fleet_id}, "test_key", algorithm="HS256")

MOCK_TOKEN = create_mock_token(1)

@pytest.mark.asyncio
@pytest.mark.timeout(10)  # Ensure test completes within 10 seconds
async def test_large_result_path():
    """Test that queries returning >100 rows provide a download_url and create the file."""
    # Mock the sql_exec function to return a large result set
    with patch('sql_assistant.main.sql_exec') as mock_sql_exec, \
         patch('sql_assistant.main.nl_to_sql') as mock_nl_to_sql, \
         patch('sql_assistant.main.answer_format') as mock_answer_format:
        
        # Generate a unique filename for testing
        test_filename = f"{uuid.uuid4()}.csv"
        test_filepath = os.path.join("static", test_filename)
        
        # Create a mock large result
        mock_sql_exec.return_value = {
            "download_url": f"/static/{test_filename}",
            "row_count": 150
        }
        mock_nl_to_sql.return_value = {"sql": "SELECT * FROM raw_telemetry LIMIT 5000"}
        mock_answer_format.return_value = "Found 150 telemetry records."
        
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
    # Mock the process_query function to return a small result set
    with patch('sql_assistant.main.process_query') as mock_process:
        # Set up mock return values for a small result set
        mock_rows = [{"id": i, "value": f"test{i}"} for i in range(10)]
        mock_process.return_value = ("Test answer", "SELECT * FROM test LIMIT 10", mock_rows, None)
        
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
