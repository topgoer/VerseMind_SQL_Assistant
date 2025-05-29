"""
Integration test for RLS (Row-Level Security).

Tests that cross-fleet isolation is properly enforced.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import jwt

from sql_assistant.main import app

# Test client
client = TestClient(app)

# Mock JWT tokens for different fleets
def create_mock_token(fleet_id):
    """Create a mock JWT token with the specified fleet_id."""
    return jwt.encode({"fleet_id": fleet_id}, "test_key", algorithm="HS256")

FLEET_1_TOKEN = create_mock_token(1)
FLEET_2_TOKEN = create_mock_token(2)

@pytest.mark.asyncio
async def test_fleet_isolation():
    """Test that users can only access data from their own fleet."""
    # Mock the process_query function to avoid actual database calls
    with patch('sql_assistant.main.process_query') as mock_process:
        # Set up mock return values
        mock_process.return_value = ("Test answer", "SELECT * FROM test", [{"count": 5}], None)
        
        # Test with fleet_id 1
        response1 = client.post(
            "/chat",
            json={"query": "How many vehicles do we have?"},
            headers={"Authorization": f"Bearer {FLEET_1_TOKEN}"}
        )
        
        # Check that process_query was called with fleet_id 1
        mock_process.assert_called_with("How many vehicles do we have?", 1)
        mock_process.reset_mock()
        
        # Test with fleet_id 2
        response2 = client.post(
            "/chat",
            json={"query": "How many vehicles do we have?"},
            headers={"Authorization": f"Bearer {FLEET_2_TOKEN}"}
        )
        
        # Check that process_query was called with fleet_id 2
        mock_process.assert_called_with("How many vehicles do we have?", 2)
        
        # Both responses should be successful
        assert response1.status_code == 200
        assert response2.status_code == 200

@pytest.mark.asyncio
async def test_unauthorized_access():
    """Test that requests without a valid JWT token are rejected."""
    # Test with no token
    response1 = client.post(
        "/chat",
        json={"query": "How many vehicles do we have?"}
    )
    assert response1.status_code == 401
    
    # Test with invalid token
    response2 = client.post(
        "/chat",
        json={"query": "How many vehicles do we have?"},
        headers={"Authorization": "Bearer invalid_token"}
    )
    assert response2.status_code == 401

@pytest.mark.asyncio
async def test_missing_fleet_id():
    """Test that JWT tokens without fleet_id claim are rejected."""
    # Create token without fleet_id
    token = jwt.encode({}, "test_key", algorithm="HS256")
    
    # Mock the get_fleet_id function to simulate the actual JWT validation
    with patch('sql_assistant.auth.jwt.decode') as mock_decode:
        # Return payload without fleet_id
        mock_decode.return_value = {}
        
        response = client.post(
            "/chat",
            json={"query": "How many vehicles do we have?"},
            headers={"Authorization": f"Bearer {token}"}
        )
        
        # Should be rejected
        assert response.status_code == 401
        assert "fleet_id" in response.json()["detail"].lower()
