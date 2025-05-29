"""
Example Python client for calling the MCP endpoint.

This script demonstrates how to call the MCP endpoint with JWT authentication.
"""
import os
import sys
import uuid
import json
import requests
from typing import Dict, Any, List, Optional

# Configuration
API_URL = os.environ.get("API_URL", "http://localhost:8000")
JWT_TOKEN = os.environ.get("JWT_TOKEN", "")

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
    if response.status_code != 200:
        error_data = response.json()
        raise Exception(f"Error calling MCP endpoint: {error_data.get('detail', 'Unknown error')}")
    
    # Return updated envelope
    return response.json()

def print_results(envelope: Dict[str, Any]) -> None:
    """
    Print the results from the MCP envelope.
    
    Args:
        envelope: MCP envelope with step outputs
    """
    print("\n=== MCP Results ===\n")
    
    # Extract step outputs
    nl_to_sql_step = next((s for s in envelope["steps"] if s["tool"] == "nl_to_sql"), None)
    sql_exec_step = next((s for s in envelope["steps"] if s["tool"] == "sql_exec"), None)
    answer_format_step = next((s for s in envelope["steps"] if s["tool"] == "answer_format"), None)
    
    # Print SQL
    if nl_to_sql_step and nl_to_sql_step.get("output"):
        print("SQL Query:")
        print(nl_to_sql_step["output"]["sql"])
        print()
    
    # Print results
    if sql_exec_step and sql_exec_step.get("output"):
        if "rows" in sql_exec_step["output"]:
            rows = sql_exec_step["output"]["rows"]
            print(f"Results ({len(rows)} rows):")
            if rows:
                # Print first 5 rows
                for i, row in enumerate(rows[:5]):
                    print(f"  Row {i+1}: {json.dumps(row)}")
                if len(rows) > 5:
                    print(f"  ... and {len(rows) - 5} more rows")
            else:
                print("  No results found")
            print()
        elif "download_url" in sql_exec_step["output"]:
            print(f"Large result set available at: {sql_exec_step['output']['download_url']}")
            print(f"Row count: {sql_exec_step['output'].get('row_count', 'unknown')}")
            print()
    
    # Print answer
    if answer_format_step and answer_format_step.get("output"):
        print("Answer:")
        print(answer_format_step["output"])
        print()

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
    
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
