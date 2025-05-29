"""
Integration test for chat vs MCP parity.

Tests that /chat and /mcp endpoints return identical answers for the same query.
"""
import pytest
import asyncio
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
async def test_chat_vs_mcp_parity():
    """Test that /chat and /mcp endpoints return identical answers for the same query."""
    # Enable MCP for testing
    with patch('sql_assistant.main.ENABLE_MCP', True):
        # Mock the process_query function to avoid actual database calls
        with patch('sql_assistant.main.process_query') as mock_process:
            # Set up mock return values
            mock_process.return_value = ("Test answer", "SELECT * FROM test", [{"count": 5}], None)
            
            # Test /chat endpoint
            chat_response = client.post(
                "/chat",
                json={"query": "How many vehicles do we have?"},
                headers={"Authorization": f"Bearer {MOCK_TOKEN}"}
            )
            
            # Test /mcp endpoint
            mcp_response = client.post(
                "/mcp",
                json={
                    "trace_id": str(uuid.uuid4()),
                    "context": {"query": "How many vehicles do we have?"},
                    "steps": [
                        {"tool": "nl_to_sql"},
                        {"tool": "sql_exec"},
                        {"tool": "answer_format"}
                    ]
                },
                headers={"Authorization": f"Bearer {MOCK_TOKEN}"}
            )
            
            # Both responses should be successful
            assert chat_response.status_code == 200
            assert mcp_response.status_code == 200
            
            # Extract answers
            chat_answer = chat_response.json()["answer"]
            mcp_answer = mcp_response.json()["steps"][2]["output"]
            
            # Answers should be identical
            assert chat_answer == mcp_answer
            
            # SQL should be identical
            chat_sql = chat_response.json()["sql"]
            mcp_sql = mcp_response.json()["steps"][0]["output"]["sql"]
            assert chat_sql == mcp_sql

@pytest.mark.asyncio
async def test_mcp_partial_steps():
    """Test that /mcp endpoint can handle partial steps."""
    # Enable MCP for testing
    with patch('sql_assistant.main.ENABLE_MCP', True):
        # Mock individual pipeline functions
        with patch('sql_assistant.main.nl_to_sql') as mock_nl_to_sql, \
             patch('sql_assistant.main.sql_exec') as mock_sql_exec, \
             patch('sql_assistant.main.answer_format') as mock_answer_format:
            
            # Set up mock return values
            mock_nl_to_sql.return_value = {"sql": "SELECT * FROM test"}
            mock_sql_exec.return_value = {"rows": [{"count": 5}]}
            mock_answer_format.return_value = "Test answer"
            
            # Test with only nl_to_sql step
            response1 = client.post(
                "/mcp",
                json={
                    "trace_id": str(uuid.uuid4()),
                    "context": {"query": "How many vehicles do we have?"},
                    "steps": [{"tool": "nl_to_sql"}]
                },
                headers={"Authorization": f"Bearer {MOCK_TOKEN}"}
            )
            
            # Should be successful
            assert response1.status_code == 200
            
            # Should have output for nl_to_sql step
            assert response1.json()["steps"][0]["output"] == {"sql": "SELECT * FROM test"}
            
            # Test with only answer_format step (should run previous steps automatically)
            response2 = client.post(
                "/mcp",
                json={
                    "trace_id": str(uuid.uuid4()),
                    "context": {"query": "How many vehicles do we have?"},
                    "steps": [{"tool": "answer_format"}]
                },
                headers={"Authorization": f"Bearer {MOCK_TOKEN}"}
            )
            
            # Should be successful
            assert response2.status_code == 200
            
            # Should have output for answer_format step
            assert response2.json()["steps"][0]["output"] == "Test answer"

@pytest.mark.asyncio
async def test_mcp_disabled():
    """Test that /mcp endpoint is disabled when ENABLE_MCP is false."""
    # Disable MCP for testing
    with patch('sql_assistant.main.ENABLE_MCP', False):
        response = client.post(
            "/mcp",
            json={
                "trace_id": str(uuid.uuid4()),
                "context": {"query": "How many vehicles do we have?"},
                "steps": [{"tool": "nl_to_sql"}]
            },
            headers={"Authorization": f"Bearer {MOCK_TOKEN}"}
        )
        
        # Should return 404 Not Found
        assert response.status_code == 404
