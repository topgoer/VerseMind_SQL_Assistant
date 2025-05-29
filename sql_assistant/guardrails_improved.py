"""
SQL guardrails for VerseMind SQL Assistant.

This module provides validation and security checks for SQL queries.
"""
import re
from typing import Tuple

# Forbidden SQL keywords that could be used for malicious purposes
FORBIDDEN_KEYWORDS = [
    "DROP", "DELETE", "TRUNCATE", "ALTER", "CREATE", "INSERT", "UPDATE", 
    "GRANT", "REVOKE", "EXECUTE", "FUNCTION", "PROCEDURE", "TRIGGER",
    "ROLE", "USER", "PASSWORD"
]

# SQL comment patterns to reject
COMMENT_PATTERNS = [
    r"--.*?$",  # Single line comments
    r"/\*.*?\*/",  # Multi-line comments
]

def extract_sql_query(input_text: str) -> str:
    """
    Extract the SQL query from input text.
    Tries to find a complete SELECT statement in the input text.
    
    Args:
        input_text: Text that may contain a SQL query
        
    Returns:
        Extracted SQL query or the original text if no query is found
    """
    # First, clean up any markdown code formatting
    cleaned_text = re.sub(r'```sql|```', '', input_text)
    
    # Remove any quotes that might wrap the SQL
    cleaned_text = re.sub(r'^([\'"`])|([\'"`])$', '', cleaned_text.strip())
    
    # Try to find a SELECT statement with LIMIT clause
    # This pattern specifically looks for a SQL query ending with LIMIT x 
    pattern = r"(SELECT\s+.+?LIMIT\s+\d+)(?:\s*;)?"
    match = re.search(pattern, cleaned_text, re.IGNORECASE | re.DOTALL)
    
    if match:
        return match.group(0).strip()
    
    # More general pattern as fallback
    sql_pattern = r"(SELECT\s+.+?WHERE.+?fleet_id\s*=\s*:fleet_id.+?)(?:;|\n\n|\Z)"
    match = re.search(sql_pattern, cleaned_text, re.IGNORECASE | re.DOTALL)
    
    if match:
        # Extract the SQL query
        sql = match.group(0).strip()
        # If there's no LIMIT in the extracted SQL, it's likely incomplete
        if not re.search(r'LIMIT\s+\d+', sql, re.IGNORECASE):
            # Try to find a LIMIT clause in the remaining text
            limit_match = re.search(r'LIMIT\s+\d+', cleaned_text[match.end():], re.IGNORECASE)
            if limit_match:
                sql += " " + limit_match.group(0)
        return sql
    else:
        # Return the original text if no SQL query is found
        return input_text.strip()

def validate_sql(sql: str) -> Tuple[bool, str]:
    """
    Validate SQL query against security guardrails.
    
    Args:
        sql: The SQL query to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Trim whitespace and ensure we have a string
    sql = str(sql).strip()
    
    # Log validation attempt
    print(f"Validating SQL: {sql[:100]}{'...' if len(sql) > 100 else ''}")
    
    # Check for forbidden keywords
    for keyword in FORBIDDEN_KEYWORDS:
        pattern = r'\b' + keyword + r'\b'
        if re.search(pattern, sql, re.IGNORECASE):
            return False, f"SQL contains forbidden keyword: {keyword}"
    
    # Check for SQL comments
    for pattern in COMMENT_PATTERNS:
        if re.search(pattern, sql, re.IGNORECASE | re.MULTILINE | re.DOTALL):
            return False, "SQL contains comments, which are not allowed"
    
    # Ensure query is SELECT only
    if not re.match(r'^\s*SELECT\b', sql, re.IGNORECASE):
        print(f"SQL validation failed: Does not start with SELECT. SQL starts with: {sql[:20]}")
        return False, "SQL must start with SELECT"
    
    # Ensure fleet_id filter is present
    if not re.search(r'WHERE\s+.*?\bfleet_id\s*=\s*:fleet_id\b', sql, re.IGNORECASE):
        return False, "SQL must contain WHERE clause with fleet_id = :fleet_id"
    
    # Ensure LIMIT is present and <= 5000
    limit_match = re.search(r'LIMIT\s+(\d+)', sql, re.IGNORECASE)
    if not limit_match:
        return False, "SQL must contain LIMIT clause"
    
    limit_value = int(limit_match.group(1))
    if limit_value > 5000:
        return False, f"LIMIT must be <= 5000, got {limit_value}"
    
    print("SQL validation successful")
    return True, ""

def validate_sql_with_extraction(input_text: str) -> Tuple[bool, str, str]:
    """
    Extract the SQL query from input text and validate it.
    
    Args:
        input_text: Text that may contain a SQL query
        
    Returns:
        Tuple of (is_valid, error_message, extracted_sql)
    """
    # Handle None or empty input
    if not input_text:
        return False, "Empty input", ""
    
    # Extract the SQL query
    extracted_sql = extract_sql_query(input_text)
    
    # Try additional extraction methods if the initial extraction doesn't look like SQL
    if not extracted_sql.upper().startswith('SELECT'):
        # Try stripping markdown code blocks
        if '```' in input_text:
            code_block_match = re.search(r'```(?:sql)?\s*(.*?)\s*```', input_text, re.DOTALL)
            if code_block_match:
                code_content = code_block_match.group(1).strip()
                if code_content.upper().startswith('SELECT'):
                    extracted_sql = code_content
        
        # Try extracting from quotes
        quote_match = re.search(r'[\'"`](SELECT\s+.*?)[\'"`]', input_text, re.IGNORECASE | re.DOTALL)
        if quote_match:
            extracted_sql = quote_match.group(1)
    
    # Validate the extracted SQL
    is_valid, message = validate_sql(extracted_sql)
    
    return is_valid, message, extracted_sql
