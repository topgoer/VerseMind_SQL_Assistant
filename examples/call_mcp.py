"""
Example Python client for calling the MCP endpoint.

This script demonstrates how to call the MCP endpoint with JWT authentication.
"""
import os
import sys
import uuid
import json
import requests
from typing import Dict, Any

# Configuration
API_URL = os.environ.get("API_URL", "http://localhost:8000")
JWT_TOKEN = os.environ.get("JWT_TOKEN", "")

class MCPError(Exception):
    """Custom exception for MCP API errors."""
    pass

def call_mcp(query: str, jwt_token: str) -> Dict[str, Any]:
    """
    Call the MCP endpoint with a natural language query.
    
    Args:
        query: Natural language query
        jwt_token: JWT token with fleet_id claim
        
    Returns:
        MCP envelope with step outputs
    """
    # Create MCP envelope
    envelope = {
        "trace_id": str(uuid.uuid4()),
        "context": {
            "query": query
        },
        "steps": [
            {"tool": "nl_to_sql"},
            {"tool": "sql_exec"},
            {"tool": "answer_format"}
        ]
    }
    
    try:
        # Call MCP endpoint
        response = requests.post(
            f"{API_URL}/mcp",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt_token}"
            },
            json=envelope
        )
        
        # Check for errors
        response.raise_for_status()  # Raises an HTTPError if the HTTP request returned an unsuccessful status code
        
        # Return updated envelope
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        error_data = {}
        try:
            error_data = response.json()
        except ValueError: # Includes JSONDecodeError
            pass # Keep error_data empty if response is not JSON
        raise MCPError(f"HTTP error calling MCP endpoint: {http_err}. Response: {error_data.get('detail', response.text)}") from http_err
    except requests.exceptions.RequestException as req_err:
        raise MCPError(f"Request error calling MCP endpoint: {req_err}") from req_err

# Helper function for printing SQL query
def _print_sql_query(nl_to_sql_step: Dict[str, Any] | None) -> None:
    if nl_to_sql_step and nl_to_sql_step.get("output"):
        print("SQL Query:")
        print(nl_to_sql_step["output"]["sql"])
        print()

# Helper function for handling and printing rows from SQL execution
def _handle_rows_output(rows: list) -> None:
    print(f"Results ({len(rows)} rows):")
    if rows:
        # Print first 5 rows
        for i, row_data in enumerate(rows[:5]):
            print(f"  Row {i+1}: {json.dumps(row_data)}")
        if len(rows) > 5:
            print(f"  ... and {len(rows) - 5} more rows")
    else:
        print("  No results found")
    print()

# Helper function for printing SQL execution results
def _print_sql_results(sql_exec_step: Dict[str, Any] | None) -> None:
    if sql_exec_step and sql_exec_step.get("output"):
        output = sql_exec_step["output"]
        if "rows" in output:
            _handle_rows_output(output["rows"])
        elif "download_url" in output:
            print(f"Large result set available at: {output['download_url']}")
            print(f"Row count: {output.get('row_count', 'unknown')}")
            print()

# Helper function for printing the final answer
def _print_answer(answer_format_step: Dict[str, Any] | None) -> None:
    if answer_format_step and answer_format_step.get("output"):
        print("Answer:")
        print(answer_format_step["output"])
        print()

def print_results(envelope: Dict[str, Any]) -> None:
    """
    Print the results from the MCP envelope.
    
    Args:
        envelope: MCP envelope with step outputs
    """
    print("\\n=== MCP Results ===\\n")
    
    # Extract step outputs
    nl_to_sql_step = next((s for s in envelope["steps"] if s["tool"] == "nl_to_sql"), None)
    sql_exec_step = next((s for s in envelope["steps"] if s["tool"] == "sql_exec"), None)
    answer_format_step = next((s for s in envelope["steps"] if s["tool"] == "answer_format"), None)
    
    _print_sql_query(nl_to_sql_step)
    _print_sql_results(sql_exec_step)
    _print_answer(answer_format_step)

def main():
    """Main function."""
    # Check for JWT token
    if not JWT_TOKEN:
        print("Error: JWT_TOKEN environment variable is required")
        sys.exit(1)
    
    # Get query from command line or prompt
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = input("Enter your query: ")
    
    try:
        # Call MCP endpoint
        envelope = call_mcp(query, JWT_TOKEN)
        
        # Print results
        print_results(envelope)
    
    except MCPError as e:
        print(f"MCP Error: {str(e)}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Request Error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
