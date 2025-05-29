"""
SQL active condition correction module.

This module provides helper functions for correcting SQL queries with active conditions.
"""
import re

# SQL pattern constants to avoid duplication
ACTIVE_VEHICLES_SQL_PATTERN = (
    "vehicles.vehicle_id IN (SELECT DISTINCT trips.vehicle_id FROM trips "
    "WHERE EXTRACT(MONTH FROM trips.start_ts) = EXTRACT(MONTH FROM CURRENT_DATE) "
    "AND EXTRACT(YEAR FROM trips.start_ts) = EXTRACT(YEAR FROM CURRENT_DATE))"
)

def detect_active_condition(sql: str) -> bool:
    """
    Detect if SQL contains an active condition.
    
    Args:
        sql: The SQL query to check
        
    Returns:
        True if active condition is present
    """
    if "active" not in sql.lower():
        return False
    
    active_pattern = r'\bactive\b\s*=\s*(true|false|1|0)'
    return bool(re.search(active_pattern, sql, re.IGNORECASE))

def get_activity_replacement(is_active_true: bool) -> str:
    """
    Get the appropriate replacement for active condition.
    
    Args:
        is_active_true: Whether we're looking for active=true
        
    Returns:
        SQL replacement text
    """
    activity_replacement = ACTIVE_VEHICLES_SQL_PATTERN
    if not is_active_true:
        # If searching for inactive, negate the condition
        activity_replacement = "NOT " + activity_replacement
    
    return activity_replacement

def replace_where_active_clause(sql: str, activity_replacement: str) -> str:
    """
    Replace WHERE clause containing active condition.
    
    Args:
        sql: Original SQL query
        activity_replacement: Replacement text for active condition
        
    Returns:
        SQL with replaced WHERE clause
    """
    where_active_pattern = r'WHERE\b[^(]*\bactive\b\s*=\s*(true|false|1|0)'
    if re.search(where_active_pattern, sql, re.IGNORECASE):
        print("🔄 Replacing WHERE clause with active condition")
        return re.sub(
            where_active_pattern,
            f"WHERE {activity_replacement}",
            sql,
            flags=re.IGNORECASE
        )
    return sql

def replace_and_active_clause(sql: str, activity_replacement: str) -> str:
    """
    Replace AND clause containing active condition.
    
    Args:
        sql: Original SQL query
        activity_replacement: Replacement text for active condition
        
    Returns:
        SQL with replaced AND clause
    """
    and_active_pattern = r'AND\b[^(]*\bactive\b\s*=\s*(true|false|1|0)'
    if re.search(and_active_pattern, sql, re.IGNORECASE):
        print("🔄 Replacing AND clause with active condition")
        return re.sub(
            and_active_pattern,
            f"AND {activity_replacement}",
            sql,
            flags=re.IGNORECASE
        )
    return sql

def direct_replace_active_condition(sql: str, activity_replacement: str) -> str:
    """
    Directly replace active condition references.
    
    Args:
        sql: Original SQL query
        activity_replacement: Replacement text for active condition
        
    Returns:
        SQL with replaced active condition
    """
    print("🔄 Direct replacement of active condition")
    return re.sub(
        r'active\s*=\s*(true|false|1|0)',
        activity_replacement,
        sql,
        flags=re.IGNORECASE
    )

def handle_complex_active_clause(sql: str) -> str:
    """
    Handle more complex active clause patterns that didn't match simple patterns.
    
    Args:
        sql: Original SQL query
        
    Returns:
        SQL with replaced active clause
    """    # Look for any WHERE/AND clauses with active
    active_clause_pattern = r'(WHERE|AND)\b[^()]*\bactive\b[^()]*\b(AND|\)|$)'
    match = re.search(active_clause_pattern, sql, re.IGNORECASE)
    
    if match:
        activity_replacement = ACTIVE_VEHICLES_SQL_PATTERN
        print(f"🔄 Found active clause: {match.group(0)}")
        # Replace the entire clause
        if match.group(1).upper() == "WHERE":
            replacement = f"WHERE {activity_replacement}"
            if match.group(2).upper() == "AND":
                replacement += " AND"
        else:  # AND
            replacement = f"AND {activity_replacement}"
            if match.group(2).upper() == "AND":
                replacement += " AND"
        
        return sql[:match.start()] + replacement + sql[match.end():]
    
    return sql

def process_active_conditions(extracted_sql: str) -> str:
    """
    Main entry point for processing active conditions in SQL.
    Handles all active condition cases in a streamlined way.
    
    Args:
        extracted_sql: The SQL query to process
        
    Returns:
        Corrected SQL query
    """
    # Skip if "active" is not in the query
    if "active" not in extracted_sql.lower():
        return extracted_sql
    
    # Standard active condition (active = TRUE)
    if detect_active_condition(extracted_sql):
        return process_standard_active_condition(extracted_sql)
    else:
        # Try complex patterns
        return process_complex_active_pattern(extracted_sql)

def process_standard_active_condition(sql: str) -> str:
    """
    Process standard active condition patterns like 'active = TRUE'.
    
    Args:
        sql: The SQL query to process
        
    Returns:
        Corrected SQL
    """
    print("🔄 Found non-existent 'active' column usage")
    
    # Determine if looking for active=true or active=false
    is_active_true = "active = TRUE" in sql.upper() or "active=TRUE" in sql.upper() or "active = 1" in sql
    
    # Get the appropriate replacement
    activity_replacement = get_activity_replacement(is_active_true)
    
    # Apply replacements in sequence
    for replacement_fn in [replace_where_active_clause, replace_and_active_clause, direct_replace_active_condition]:
        modified_sql = replacement_fn(sql, activity_replacement)
        if modified_sql != sql:
            print("🔄 After active replacement: " + modified_sql[:150] + "...")
            return modified_sql
    
    # No replacements made
    return sql

def process_complex_active_pattern(sql: str) -> str:
    """
    Process complex active patterns that don't match standard 'active = TRUE'.
    
    Args:
        sql: The SQL query to process
        
    Returns:
        Corrected SQL
    """
    print("⚠️ Found 'active' keyword but no direct match with =TRUE/FALSE pattern")
    
    # Try complex pattern matching
    modified_sql = handle_complex_active_clause(sql)
    
    if modified_sql != sql:
        print("🔄 After active clause replacement: " + modified_sql[:150] + "...")
        return modified_sql
    
    return sql
