"""
Database operations for SQL Assistant.

This module provides database operations functionality for:
1. Executing SQL queries
2. Handling row fetching and error cases
3. Exporting large result sets to CSV
"""
import os
import uuid
import csv
import re
from typing import Dict, List, Any, Tuple, Optional
import sqlalchemy as sa

# Constants
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

async def execute_sql_query(conn, sql: str, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Execute a SQL query and handle row mapping.
    
    Args:
        conn: Database connection
        sql: SQL query to execute
        params: Query parameters
        
    Returns:
        Tuple of (rows, error_message)
    """
    try:
        # Execute query with parameters
        result = await conn.execute(
            sa.text(sql),
            params
        )
        
        # Fetch all rows - handle potential mapping errors
        rows = []
        try:
            rows = [dict(row) for row in result.mappings()]
        except Exception as mapping_error:
            print(f"Error mapping rows: {str(mapping_error)}")
            # Try alternative approach
            try:
                rows = [dict(zip(result.keys(), row)) for row in result.fetchall()]
            except Exception as fetch_error:
                print(f"Error fetching rows: {str(fetch_error)}")
                # Last resort: return empty rows with error
                return [], f"Error processing results: {str(fetch_error)}"
        
        return rows, None
    except Exception as query_error:
        print(f"Query execution error: {str(query_error)}")
        return [], str(query_error)

def handle_large_result(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Export large result sets to CSV files and return download URL.
    
    Args:
        rows: Query result rows
        
    Returns:
        Dict with download URL and row count
    """
    # Generate unique filename
    filename = f"{uuid.uuid4()}.csv"
    filepath = os.path.join(STATIC_DIR, filename)
    
    # Write to CSV
    with open(filepath, 'w', newline='') as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        else:
            writer = csv.writer(f)
            writer.writerow(["No results"])
    
    # Return download URL
    return {
        "download_url": f"/static/{filename}",
        "row_count": len(rows)
    }

def handle_column_error(bad_column: str, column_corrections: Dict[str, str]) -> Optional[str]:
    """
    Handle column does not exist errors by finding potential corrections.
    
    Args:
        bad_column: Column name that doesn't exist
        column_corrections: Dictionary of column corrections
        
    Returns:
        Corrected column name or None if no correction found
    """
    # Check if we have a correction for this column
    for incorrect, correct in column_corrections.items():
        if incorrect.lower() == bad_column.lower():
            return correct
    return None

def extract_bad_column(error_str: str) -> Optional[str]:
    """
    Extract bad column name from error message.
    
    Args:
        error_str: Error message string
        
    Returns:
        Bad column name or None
    """
    if "column" in error_str and "does not exist" in error_str:
        column_match = re.search(r'column ([A-Za-z0-9_.]+) does not exist', error_str)
        if column_match:
            return column_match.group(1)
    return None
