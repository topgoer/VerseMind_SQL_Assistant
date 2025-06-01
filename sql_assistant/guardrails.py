"""
SQL guardrails for VerseMind SQL Assistant.

This module provides validation and security checks for SQL queries.
"""
import re
import yaml
from typing import Tuple, Dict
from pathlib import Path
from .services.domain_glossary import DOMAIN_GLOSSARY

# Load semantic mappings
semantic_mapping_path = Path(__file__).parent / "services" / "semantic_mapping.yaml"
with open(semantic_mapping_path, "r", encoding="utf-8") as f:
    SEMANTIC_MAPPINGS = yaml.safe_load(f)["mappings"]

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

with open('sql_assistant/services/business_rules.yaml', 'r', encoding='utf-8') as f:
    BUSINESS_RULES = yaml.safe_load(f)

def get_database_context() -> Dict:
    """
    Get database context including schema and sample data.
    This should be populated from your actual database.
    """
    return {
        "tables": {
            "vehicles": {
                "columns": {
                    "vehicle_id": "integer",
                    "fleet_id": "integer",
                    "model": "varchar",
                    "status": "varchar",
                    "last_maintenance": "timestamp"
                },
                "sample_data": [
                    {"vehicle_id": 1, "fleet_id": 1, "model": "Tesla Model 3", "status": "active"},
                    {"vehicle_id": 2, "fleet_id": 1, "model": "Tesla Model Y", "status": "active"}
                ]
            },
            "vehicle_energy_usage": {
                "columns": {
                    "vehicle_id": "integer",
                    "timestamp": "timestamp",
                    "energy_consumed": "decimal",
                    "battery_level": "decimal"
                },
                "sample_data": [
                    {"vehicle_id": 1, "timestamp": "2024-03-20 10:00:00", "energy_consumed": 15.5, "battery_level": 85.0},
                    {"vehicle_id": 2, "timestamp": "2024-03-20 10:00:00", "energy_consumed": 12.3, "battery_level": 90.0}
                ]
            }
        },
        "relationships": [
            "vehicles.vehicle_id -> vehicle_energy_usage.vehicle_id"
        ]
    }

def get_semantic_context(user_question: str) -> Dict:
    """
    Extract semantic context from user question using mappings and glossary.
    
    Args:
        user_question: The user's natural language question
        
    Returns:
        Dictionary containing semantic context
    """
    context = {
        "mapped_terms": {},
        "domain_terms": {},
        "tables": set(),
        "columns": set()
    }
    
    # Find mapped terms in the question
    for term, mapping in SEMANTIC_MAPPINGS.items():
        if term.lower() in user_question.lower():
            table, column = mapping.split(".")
            context["mapped_terms"][term] = mapping
            context["tables"].add(table)
            context["columns"].add(column)
    
    # Find domain terms in the question
    for term, info in DOMAIN_GLOSSARY.items():
        if term.lower() in user_question.lower():
            context["domain_terms"][term] = info
    
    return context

def generate_prompt(user_question: str) -> str:
    """
    Generate a complete prompt for the LLM including database context and user question.
    
    Args:
        user_question: The user's natural language question
        
    Returns:
        Complete prompt for the LLM
    """
    db_context = get_database_context()
    
    prompt = f"""You are a SQL expert. Given the following database context and user question, generate a valid PostgreSQL query.

Database Schema:
{format_schema(db_context)}

User Question:
{user_question}

Requirements:
1. The query must be a SELECT statement
2. The query must include WHERE fleet_id = :fleet_id
3. The query must include a LIMIT clause (max 5000)
4. The query must be valid PostgreSQL syntax
5. The query should answer the user's question using the available tables and columns

Please generate a SQL query that meets these requirements.
"""
    return prompt

def format_schema(db_context: Dict) -> str:
    """Format database schema for the prompt."""
    schema = []
    for table_name, table_info in db_context["tables"].items():
        columns = [f"{col_name} ({col_type})" for col_name, col_type in table_info["columns"].items()]
        schema.append(f"Table: {table_name}")
        schema.append("Columns:")
        schema.extend(f"  - {col}" for col in columns)
        schema.append("")
    
    schema.append("Relationships:")
    schema.extend(f"  - {rel}" for rel in db_context["relationships"])
    return "\n".join(schema)

def extract_sql_query(input_text: str) -> str:
    """
    Extract the SQL query from input text.
    Tries to find a complete SELECT statement in the input text.
    
    Args:
        input_text: Text that may contain a SQL query
        
    Returns:
        Extracted SQL query or the original text if no query is found
    """
    # Try to find a SELECT statement with LIMIT clause
    # This pattern specifically looks for a SQL query ending with LIMIT x 
    pattern = r"(SELECT\s+.*?LIMIT\s+\d+)(?:\s*;)?"
    match = re.search(pattern, input_text, re.IGNORECASE | re.DOTALL)
    
    if match:
        return match.group(0).strip()
    
    # More general pattern as fallback
    sql_pattern = r"(SELECT\s+.*?WHERE\s+.*?fleet_id\s*=\s*:fleet_id\b.*)(?:;|\n\n|\Z)"
    match = re.search(sql_pattern, input_text, re.IGNORECASE | re.DOTALL)
    
    if match:
        # Extract the SQL query
        sql = match.group(0).strip()
        # If there's no LIMIT in the extracted SQL, it's likely incomplete
        if not re.search(r'LIMIT\s+\d+', sql, re.IGNORECASE):
            # Try to find a LIMIT clause in the remaining text
            limit_match = re.search(r'LIMIT\s+\d+', input_text[match.end():], re.IGNORECASE)
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
    
    # Validate the extracted SQL
    is_valid, message = validate_sql(extracted_sql)
    
    return is_valid, message, extracted_sql
