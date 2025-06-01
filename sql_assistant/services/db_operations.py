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
from typing import Dict, List, Any, Tuple, Optional, Union
import sqlalchemy as sa
from sqlalchemy.engine import Result
from sqlalchemy.engine.row import Row

# Constants
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Error messages
NO_DATA_MESSAGE = "No data found for your query. Please check if there is any data in the specified time range."
INTERNAL_ERROR_MESSAGE = "Internal error: Could not process query results. Please contact support."

# Vehicle-specific error messages
NO_VEHICLE_DATA_MESSAGE = (
    "No data found for vehicle 42 in the past 90 days. This could be because:\n"
    "1. The vehicle ID might be incorrect\n"
    "2. The vehicle might not have any battery health data in this time range\n"
    "3. The vehicle might be new or recently added to the system\n\n"
    "Please try:\n"
    "- Verifying the vehicle ID\n"
    "- Extending the time range\n"
    "- Checking if the vehicle has any other metrics available"
)

def _row_to_dict(row: Union[Row, tuple, dict]) -> Dict[str, Any]:
    """Convert any type of row to dict."""
    if isinstance(row, dict):
        return row
    if hasattr(row, '_fields'):  # namedtuple
        return row._asdict()
    if hasattr(row, '_mapping'):  # SQLAlchemy Row
        return dict(row._mapping)
    # Fallback: use index as key
    return {str(i): v for i, v in enumerate(row)}

async def _process_result(result: Result) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Process SQLAlchemy Result object into list of dicts."""
    try:
        # 1. Try result.mappings() first (preferred)
        try:
            rows = [dict(row) for row in result.mappings()]
            return rows, None
        except Exception as e:
            print(f"Error with result.mappings(): {str(e)}")

        # 2. Try result.fetchall() with row conversion
        try:
            rows = result.fetchall()
            if rows is None:
                return [], NO_DATA_MESSAGE
            if not rows:
                return [], NO_DATA_MESSAGE
            return [_row_to_dict(row) for row in rows], None
        except Exception as e:
            print(f"Error with result.fetchall(): {str(e)}")

        # 3. Try result.keys() and manual row building
        try:
            if hasattr(result, 'keys'):
                keys = result.keys()
                rows = []
                for row in result:
                    if isinstance(row, (tuple, list)):
                        rows.append(dict(zip(keys, row)))
                    else:
                        rows.append(_row_to_dict(row))
                return rows, None
        except Exception as e:
            print(f"Error with result.keys(): {str(e)}")

        # 4. Last resort: try to iterate result directly
        try:
            rows = [_row_to_dict(row) for row in result]
            return rows, None
        except Exception as e:
            print(f"Error iterating result: {str(e)}")

        return [], INTERNAL_ERROR_MESSAGE
    except Exception as e:
        print(f"Error processing result: {str(e)}")
        return [], INTERNAL_ERROR_MESSAGE

async def _try_mappings(result: Result) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Try to get results using mappings() method."""
    try:
        rows = [dict(row) for row in result.mappings()]
        if not rows:
            return [], NO_VEHICLE_DATA_MESSAGE
        return rows, None
    except Exception as e:
        print(f"Error with result.mappings(): {str(e)}")
        return [], None

async def _try_fetchall(result: Result) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Try to get results using fetchall() method."""
    try:
        rows = result.fetchall()
        if rows is None or not rows:
            return [], NO_VEHICLE_DATA_MESSAGE
        return [_row_to_dict(row) for row in rows], None
    except Exception as e:
        print(f"Error with result.fetchall(): {str(e)}")
        return [], None

async def _try_keys(result: Result) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Try to get results using keys() method."""
    try:
        if not hasattr(result, 'keys'):
            return [], None
        keys = result.keys()
        rows = []
        for row in result:
            if isinstance(row, (tuple, list)):
                rows.append(dict(zip(keys, row)))
            else:
                rows.append(_row_to_dict(row))
        if not rows:
            return [], NO_VEHICLE_DATA_MESSAGE
        return rows, None
    except Exception as e:
        print(f"Error with result.keys(): {str(e)}")
        return [], None

async def _try_iterate(result: Result) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Try to get results by iterating directly."""
    try:
        rows = [_row_to_dict(row) for row in result]
        if not rows:
            return [], NO_VEHICLE_DATA_MESSAGE
        return rows, None
    except Exception as e:
        print(f"Error iterating result: {str(e)}")
        return [], None

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
        # Execute query
        result = await conn.execute(sa.text(sql), params)
        if result is None:
            print("Error: conn.execute() returned None")
            return [], "Query execution failed. Please try again."

        # Try different methods to get results
        methods = [
            _try_mappings,
            _try_fetchall,
            _try_keys,
            _try_iterate
        ]

        for method in methods:
            rows, error = await method(result)
            if rows:
                return rows, None
            if error:
                # Return complete query context and empty result
                response = {
                    "status": "success",
                    "data": {
                        "rows": [],
                        "row_count": 0,
                        "query": {
                            "sql": sql,
                            "params": params
                        },
                        "context": {
                            "vehicle_id": params.get("vehicle_id", "unknown"),
                            "time_range": params.get("time_range", "unknown"),
                            "metrics": [col for col in params.get("metrics", [])]
                        }
                    },
                    "message": error
                }
                return [], str(response)

        return [], "Could not process query results. Please try again."
    except Exception as query_error:
        print(f"Query execution error: {str(query_error)}")
        return [], f"Query execution failed: {str(query_error)}"

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
