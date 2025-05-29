"""
SQL correction utilities for VerseMind SQL Assistant.

This module handles SQL validation and correction.
"""
import re
from typing import Tuple

from sql_assistant.guardrails import validate_sql

# SQL pattern constants to avoid duplication
ACTIVE_VEHICLES_SQL_PATTERN = (
    "vehicles.vehicle_id IN (SELECT DISTINCT trips.vehicle_id FROM trips "
    "WHERE EXTRACT(MONTH FROM trips.start_ts) = EXTRACT(MONTH FROM CURRENT_DATE) "
    "AND EXTRACT(YEAR FROM trips.start_ts) = EXTRACT(YEAR FROM CURRENT_DATE))"
)

def check_sql_content(sql_text, error_message):
    """Helper function to check if SQL content is valid."""
    if not sql_text:
        print(error_message)
        raise ValueError(error_message)

def is_valid_sql(sql_text):
    """Check if text contains valid SQL elements."""
    return "SELECT" in sql_text.upper()

def correct_active_conditions(extracted_sql: str) -> str:
    """
    Detect and fix 'active = TRUE' conditions in SQL queries.
    
    Args:
        extracted_sql: The SQL query to process
        
    Returns:
        Corrected SQL query
    """
    # Delegate the complexity to the active_conditions module
    from sql_assistant.services.active_conditions import process_active_conditions
    
    # Process all active conditions correction in one call
    return process_active_conditions(extracted_sql)

def _replace_direct_last_active_date(extracted_sql: str) -> str:
    """Replace direct last_active_date column references."""
    last_active_replacement = "(SELECT MAX(trips.start_ts) FROM trips WHERE trips.vehicle_id = vehicles.vehicle_id)"
    
    # Replace all instances of last_active_date with the subquery
    extracted_sql = re.sub(
        r'\blast_active_date\b',
        last_active_replacement,
        extracted_sql,
        flags=re.IGNORECASE
    )
    
    print("🔄 After last_active_date replacement: " + extracted_sql[:150] + "...")
    return extracted_sql

def _determine_replacement_text(match_text: str) -> str:
    """Determine the appropriate replacement text based on context."""
    last_active_replacement = "(SELECT MAX(trips.start_ts) FROM trips WHERE trips.vehicle_id = vehicles.vehicle_id)"
    
    if "MONTH" in match_text.upper() and "EXTRACT" in match_text.upper():
        # If checking for same month, replace with activity check
        return ACTIVE_VEHICLES_SQL_PATTERN
    else:
        # Just use direct last_active_date replacement
        return last_active_replacement

def _build_replacement_clause(match, replacement_text: str) -> str:
    """Build the replacement clause based on WHERE/AND context."""
    if match.group(1).upper() == "WHERE":
        replacement = f"WHERE {replacement_text}"
        if match.group(2).upper() == "AND":
            replacement += " AND"
    else:  # AND
        replacement = f"AND {replacement_text}"
        if match.group(2).upper() == "AND":
            replacement += " AND"
    
    return replacement

def _handle_last_active_clause(extracted_sql: str) -> str:
    """Handle complex last_active clause replacements."""
    print("⚠️ Found 'last_active_date' keyword but no direct match with exact column name")
    last_active_clause_pattern = r'(WHERE|AND)\b[^()]*\blast_active[^()]*\b(AND|\)|$)'
    match = re.search(last_active_clause_pattern, extracted_sql, re.IGNORECASE)
    
    if not match:
        return extracted_sql
    
    print(f"🔄 Found last_active clause: {match.group(0)}")
    
    # Determine replacement text based on context
    replacement_text = _determine_replacement_text(match.group(0))
    
    # Build the replacement clause
    replacement = _build_replacement_clause(match, replacement_text)
    
    # Apply the replacement
    extracted_sql = extracted_sql[:match.start()] + replacement + extracted_sql[match.end():]
    print("🔄 After last_active clause replacement: " + extracted_sql[:150] + "...")
    
    return extracted_sql

def correct_last_active_date(extracted_sql: str) -> str:
    """
    Fix references to non-existent 'last_active_date' column.
    
    Args:
        extracted_sql: The SQL query to process
        
    Returns:
        Corrected SQL query
    """
    # Skip if "last_active_date" is not in the query
    if "last_active_date" not in extracted_sql.lower():
        return extracted_sql
    
    last_active_pattern = r'\blast_active_date\b'
    match = re.search(last_active_pattern, extracted_sql, re.IGNORECASE)
    
    if match:
        print(f"🔄 Found non-existent 'last_active_date' column usage: {match.group(0)}")
        return _replace_direct_last_active_date(extracted_sql)
    else:
        return _handle_last_active_clause(extracted_sql)

def ensure_trips_join(extracted_sql: str) -> str:
    """
    Ensure trips table is included in the FROM clause if checking activity.
    
    Args:
        extracted_sql: The SQL query to process
        
    Returns:
        Corrected SQL query with necessary JOIN
    """
    # Check if we need to add trips JOIN
    needs_join = (("vehicle_id IN (SELECT DISTINCT trips.vehicle_id" in extracted_sql or 
                  "MAX(trips.start_ts)" in extracted_sql) and 
                  "JOIN trips" not in extracted_sql.upper() and 
                  "FROM trips" not in extracted_sql.upper())
    
    if not needs_join:
        return extracted_sql
    
    print("🔄 Added missing JOIN with trips table")
    
    # Add trips JOIN to FROM clause if needed
    if "FROM vehicles" in extracted_sql:
        extracted_sql = re.sub(
            r'FROM\s+vehicles\b([^J]*)(WHERE|GROUP|ORDER|HAVING|LIMIT|$)',
            r'FROM vehicles LEFT JOIN trips ON vehicles.vehicle_id = trips.vehicle_id\1\2',
            extracted_sql,
            flags=re.IGNORECASE
        )
    
    print("🔄 After JOIN addition: " + extracted_sql[:150] + "...")
    return extracted_sql

def attempt_aggressive_extraction(sql: str) -> Tuple[bool, str]:
    """
    Try an aggressive SQL extraction as last-resort recovery.
    
    Args:
        sql: The original SQL-containing text
        
    Returns:
        Tuple of (success, extracted_sql)
    """
    contains_code_block = '```' in sql
    contains_select = "SELECT" in sql.upper()
    
    if not (contains_code_block or contains_select):
        return False, ""
    
    print("Attempting more aggressive SQL extraction...")
    select_pattern = r"SELECT\s+.+?WHERE.+?fleet_id\s*=\s*:fleet_id.+?LIMIT\s+\d+"
    select_match = re.search(select_pattern, sql, re.IGNORECASE | re.DOTALL)
    
    if not select_match:
        return False, ""
    
    extracted_try2 = select_match.group(0)
    is_valid2, _ = validate_sql(extracted_try2)
    
    if is_valid2:
        print("✅ Second extraction attempt successful")
        return True, extracted_try2
    
    return False, ""
