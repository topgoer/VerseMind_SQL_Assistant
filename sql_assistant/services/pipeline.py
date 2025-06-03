"""
Pipeline service for SQL Assistant.

This module provides the core functionality for:
1. Converting natural language to SQL
2. Executing SQL queries
3. Formatting results into human-readable answers
"""
import os
import json
import re
import httpx
from typing import Dict, Optional, Any
import yaml
import anthropic
from mistralai.client import MistralClient
import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from openai import AsyncOpenAI
from sql_assistant.schemas.generate_sql import GenerateSQLParameters
from sql_assistant.guardrails import validate_sql_with_extraction, extract_sql_query
from sql_assistant.services.domain_glossary import DOMAIN_GLOSSARY
from sql_assistant.services.sql_correction import (
    is_valid_sql, correct_active_conditions,
    correct_last_active_date, ensure_trips_join, attempt_aggressive_extraction
)
from sql_assistant.services.llm_provider import (
    check_llm_api_keys
)
from sql_assistant.services.error_handler import error_handler
from sql_assistant.services.db_operations import execute_sql_query

load_dotenv()

# Constants
FLEET_ID_PLACEHOLDER = ":fleet_id"

def _fix_vehicle_energy_usage(sql: str) -> str:
    """Fix hallucinated vehicle_energy_usage table references."""
    if "vehicle_energy_usage" not in sql:
        return sql
        
    # Heuristically decide whether this was intended as battery health or charging info
    if "energy_consumed" in sql or "charging" in sql:
        sql = sql.replace("vehicle_energy_usage", "charging_sessions")
        sql = sql.replace("timestamp", "start_ts")
        sql = sql.replace("energy_consumed", "energy_delivered_kwh")
    else:
        sql = sql.replace("vehicle_energy_usage", "battery_cycles")
        sql = sql.replace("timestamp", "ts")
        sql = sql.replace("energy_consumed", "soh_pct")
    return sql

def _fix_last_active_date(sql: str) -> str:
    """Fix hallucinated last_active_date column references."""
    if "last_active_date" not in sql:
        return sql
        
    sql = sql.replace("last_active_date", "t.start_ts")
    if "FROM vehicles" in sql and "JOIN trips" not in sql:
        sql = sql.replace("FROM vehicles", "FROM vehicles v JOIN trips t ON v.vehicle_id = t.vehicle_id")
    if "vehicles." in sql:
        sql = sql.replace("vehicles.", "v.")
    return sql

def _fix_datetime_columns(sql: str) -> str:
    """Fix wrong datetime column names."""
    return sql.replace("start_time", "start_ts").replace("end_time", "end_ts")

def _fix_bad_aliases(sql: str) -> str:
    """Fix bad table aliases."""
    if "veu." not in sql:
        return sql
        
    sql = sql.replace("veu.timestamp", "bc.ts")
    sql = sql.replace("veu.energy_consumed", "bc.soh_pct")
    sql = sql.replace("veu.", "bc.")
    return sql

def _fix_duplicate_limits(sql: str) -> str:
    """Fix duplicate LIMIT clauses."""
    if "LIMIT" not in sql.upper():
        return sql
        
    # Find all LIMIT clauses
    limit_matches = re.finditer(r'LIMIT\s+(\d+)', sql, re.IGNORECASE)
    limits = [m.group(0) for m in limit_matches]
    
    if len(limits) > 1:
        # Keep the first LIMIT clause and remove others
        keep_limit = limits[0]
        
        # Remove all LIMIT clauses
        for limit in limits:
            sql = sql.replace(limit, "")
            
        # Add back the first LIMIT
        sql = sql.rstrip() + f" {keep_limit}"
        
        # Clean up any extra whitespace
        sql = re.sub(r'\s+', ' ', sql).strip()
        
        print(f"Fixed duplicate LIMIT clauses. Keeping: {keep_limit}")
    return sql

def fix_hallucinated_sql(sql: str) -> str:
    """
    Replace known hallucinated table/column names with valid schema names.
    Also patches incorrect aliases or date columns where necessary.
    """
    # First fix any hallucinated tables/columns
    sql = _fix_vehicle_energy_usage(sql)
    sql = _fix_last_active_date(sql)
    sql = _fix_datetime_columns(sql)
    sql = _fix_bad_aliases(sql)
    
    # Then fix LIMIT clauses
    sql = _fix_duplicate_limits(sql)
    
    return sql

# Get the absolute path to the services directory
SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))

# Database connection
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "sql_assistant")
DATABASE_URL = os.getenv("DATABASE_URL", f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
engine = create_async_engine(DATABASE_URL)

# Static directory for CSV downloads
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Load configuration files with error handling
def load_yaml_config(filename: str, required_key: str = None) -> dict:
    """Load a YAML configuration file with error handling."""
    filepath = os.path.join(SERVICES_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
            if config is None:
                raise ValueError(f"Empty configuration file: {filename}")
            if required_key and required_key not in config:
                raise ValueError(f"Missing required key '{required_key}' in {filename}")
            return config[required_key] if required_key else config
    except FileNotFoundError:
        raise ValueError(f"Configuration file not found: {filename}")
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {filename}: {str(e)}")
    except Exception as e:
        raise ValueError(f"Error loading {filename}: {str(e)}")

# Load all configuration files
try:
    print("\n=== Loading Configuration Files ===")
    print("Loading semantic_mapping.yaml...")
    semantic_mappings = load_yaml_config('semantic_mapping.yaml', 'mappings')
    print("Loading database_schema.yaml...")
    database_schema = load_yaml_config('database_schema.yaml')
    print("Loading business_rules.yaml...")
    BUSINESS_RULES = load_yaml_config('business_rules.yaml')
    print("=== Configuration Files Loaded ===\n")
    # Configuration file assertion checks
    assert isinstance(database_schema, dict), "database_schema must be a dict, got {}".format(type(database_schema))
    assert 'tables' in database_schema and isinstance(database_schema['tables'], dict), "database_schema['tables'] must be a dict"
    assert 'critical_info' in database_schema and isinstance(database_schema['critical_info'], list), "database_schema['critical_info'] must be a list"
    assert isinstance(semantic_mappings, dict), "semantic_mappings must be a dict"
    assert isinstance(BUSINESS_RULES, dict), "BUSINESS_RULES must be a dict"
    assert 'rules' in BUSINESS_RULES and isinstance(BUSINESS_RULES['rules'], list), "BUSINESS_RULES['rules'] must be a list"
except ValueError as e:
    print(f"Configuration error: {str(e)}")
    raise
except AssertionError as e:
    print(f"Configuration assertion error: {str(e)}")
    raise

# Define constants for column references
TRIPS_DISTANCE_KM = "trips.distance_km"
TRIPS_ENERGY = "trips.energy"
TRIPS_ENERGY_KWH = "trips.energy_kwh"

COLUMN_CORRECTIONS = {
    TRIPS_ENERGY: TRIPS_ENERGY_KWH,     # Common simplification of energy_kwh
    "energy_consumed": "energy_kwh",        # Common incorrect reference
    "energy_usage": "energy_kwh",           # Common incorrect reference
    "vehicle.id": "vehicles.vehicle_id",    # Common incorrect reference
    "trip.id": "trips.trip_id",             # Common incorrect reference
    "driver.id": "drivers.driver_id",       # Common incorrect reference
    "trips.driver_id": "drivers.driver_id", # Incorrect join reference
    "trip_distance": TRIPS_DISTANCE_KM,       # Common incorrect reference
    "distance": TRIPS_DISTANCE_KM,            # Common simplified reference
    "idle_min": "trips.idle_minutes",       # Common simplification
    "duration": "trips.end_ts - trips.start_ts", # Common duration calculation
    "registration": "vehicles.registration_no", # Common simplification
    "temp_c": "trips.avg_temp_c",           # Common simplification
    "trip_date": "trips.start_ts::date"     # Common date extraction
}

SEMANTIC_MAPPING_YAML = 'semantic_mapping.yaml'

TROUBLE_MSG = "I'm having trouble processing your query. Could you please rephrase it?"

def get_available_llm_providers():
    providers = []
    if os.environ.get("DEEPSEEK_API_KEY"):
        providers.append("deepseek")
    if os.environ.get("OPENAI_API_KEY"):
        providers.append("openai")
    if os.environ.get("ANTHROPIC_API_KEY"):
        providers.append("anthropic")
    if os.environ.get("MISTRAL_API_KEY"):
        providers.append("mistral")
    return providers

def get_field_list_from_semantic_mapping():
    filepath = os.path.join(SERVICES_DIR, SEMANTIC_MAPPING_YAML)
    with open(filepath, 'r', encoding='utf-8') as f:
        mapping = yaml.safe_load(f)
    # Only take values, remove duplicates
    fields = sorted(set(mapping['mappings'].values()))
    return '\n'.join(fields)

def get_semantic_mapping_prompt():
    filepath = os.path.join(SERVICES_DIR, SEMANTIC_MAPPING_YAML)
    with open(filepath, 'r', encoding='utf-8') as f:
        mapping = yaml.safe_load(f)
    lines = ["user term → table.column"]
    lines.append("------------------------")
    for k, v in mapping['mappings'].items():
        lines.append(f"{k} → {v}")
    return '\n'.join(lines), set(mapping['mappings'].values())

def find_invalid_fields(sql, allowed_fields):
    # Roughly extract field names (table.column) from SQL using regex
    used_fields = set(re.findall(r'([a-zA-Z_]+\.[a-zA-Z_]+)', sql))
    return [f for f in used_fields if f not in allowed_fields]

def _process_sql_result(sql: str, allowed_fields, prompt, provider_idx):
    invalid_fields = find_invalid_fields(sql, allowed_fields)
    if invalid_fields:
        _, corrected_sql = error_handler.detect_error(sql, f"column {invalid_fields[0]} does not exist")
        if corrected_sql:
            print(f"Auto-corrected SQL: {corrected_sql}")
            sql = corrected_sql
        else:
            print(f"Invalid fields detected: {invalid_fields}")
            raise ValueError(f"Invalid fields in SQL: {invalid_fields}")
    return {
        "sql": sql,
        "is_fallback": provider_idx != 0,
        "prompt": prompt,
        "allowed_fields": allowed_fields
    }

def _remove_llm_limits(sql: str) -> str:
    """Remove any LIMIT clauses from the SQL query."""
    return re.sub(r'\s+LIMIT\s+\d+', '', sql, flags=re.IGNORECASE)

def _add_default_limit(sql: str) -> str:
    """Add default LIMIT 5000 to SQL."""
    return sql.rstrip() + " LIMIT 5000"

def _validate_and_extract_sql(sql: str) -> str:
    """
    Validate SQL against guardrails with extraction and return the extracted SQL.
    
    Args:
        sql: The SQL query to validate and extract
        
    Returns:
        The extracted SQL query
        
    Raises:
        ValueError: If the SQL is invalid or empty
    """
    # Check for None or empty input first
    if sql is None:
        raise ValueError("Null SQL response from LLM")
        
    # Check for empty string
    if not sql.strip():
        raise ValueError("Empty SQL response from LLM")
    
    print("Raw LLM output received for SQL extraction: {}{}".format(
        sql[:200], '...' if len(sql) > 200 else ''))
    
    # First try to extract the SQL part
    extracted_sql = extract_sql_query(sql)
    if not extracted_sql:
        raise ValueError("Failed to extract SQL from LLM response")
        
    print("Extracted SQL: {}".format(extracted_sql))
    
    # Check if extraction resulted in something that looks like SQL
    if not is_valid_sql(extracted_sql):
        print("SQL extraction failed to produce valid SQL")
        raise ValueError("Failed to extract valid SQL from LLM response")
    
    # SCHEMA CORRECTION: Before validation, fix common issues with the schema
    print("Starting schema correction...")
    original_sql = extracted_sql
    
    # 0. First, correct invalid column references
    extracted_sql = _correct_invalid_columns(extracted_sql)
    
    # 1. Fix active = TRUE conditions
    extracted_sql = correct_active_conditions(extracted_sql)
    
    # 2. Fix last_active_date references
    extracted_sql = correct_last_active_date(extracted_sql)
    
    # 3. Ensure trips table is included in FROM clause if needed
    extracted_sql = ensure_trips_join(extracted_sql)
    
    # 4. Fix hallucinated SQL
    extracted_sql = fix_hallucinated_sql(extracted_sql)
    
    # 5. Remove any LIMITs from LLM and add our default LIMIT
    extracted_sql = _remove_llm_limits(extracted_sql)
    extracted_sql = _add_default_limit(extracted_sql)
    
    # 6. Check if any modifications were made and log them
    if extracted_sql != original_sql:
        print("✅ Schema corrections applied to the SQL query")
        print(f"BEFORE: {original_sql}")
        print(f"AFTER:  {extracted_sql}")
    else:
        print("✓ No schema corrections needed")
    
    # 7. Now validate SQL syntax (not schema correctness)
    print("Validating SQL: {}".format(extracted_sql[:50] + "..."))
    is_valid, error_message, _ = validate_sql_with_extraction(extracted_sql)
    
    if not is_valid:
        print(f"⚠️ SQL validation failed: {error_message}")
        
        # Make one more attempt with aggressive extraction
        success, extracted_try2 = attempt_aggressive_extraction(sql)
        if success:
            return extracted_try2
            
        raise ValueError(f"Generated SQL failed validation: {error_message}")
    else:
        print("✅ SQL validation successful")
    
    # 8. Final check for empty or invalid SQL
    if not extracted_sql or not is_valid_sql(extracted_sql):
        raise ValueError("Validation returned empty or invalid SQL")
    
    # 9. Always return our corrected version, not what the validator returned
    # This ensures our schema corrections are preserved
    print("Final SQL to be returned: " + extracted_sql[:100] + "...")
    return extracted_sql

# Dictionary containing allowed column names by table
# This helps catch references to non-existent columns
TABLE_COLUMNS = {
    "vehicles": ["vehicle_id", "vin", "fleet_id", "model", "make", "variant", "registration_no", "purchase_date"],
    "trips": ["trip_id", "vehicle_id", "start_ts", "end_ts", "distance_km", "energy_kwh", "idle_minutes", "avg_temp_c"],
    "charging_sessions": ["session_id", "vehicle_id", "start_ts", "end_ts", "start_soc", "end_soc", "energy_kwh", "location"],
    "drivers": ["driver_id", "fleet_id", "name", "license_no", "hire_date"],
    "fleets": ["fleet_id", "name", "country", "time_zone"],
    "alerts": ["alert_id", "vehicle_id", "alert_type", "severity", "alert_ts", "value", "threshold", "resolved_bool", "resolved_ts"],
    "battery_cycles": ["cycle_id", "vehicle_id", "ts", "dod_pct", "soh_pct"],
    "raw_telemetry": ["ts", "vehicle_id", "soc_pct", "pack_voltage_v", "pack_current_a", "batt_temp_c", "latitude", "longitude", "speed_kph", "odo_km"],
    "processed_metrics": ["ts", "vehicle_id", "avg_speed_kph_15m", "distance_km_15m", "energy_kwh_15m", "battery_health_pct", "soc_band"],
    "maintenance_logs": ["maint_id", "vehicle_id", "maint_type", "start_ts", "end_ts", "cost_sgd", "notes"],
    "geofence_events": ["event_id", "vehicle_id", "geofence_name", "enter_ts", "exit_ts"],
    "fleet_daily_summary": ["fleet_id", "date", "total_distance_km", "total_energy_kwh", "active_vehicles", "avg_soc_pct"],
    "driver_trip_map": ["trip_id", "driver_id", "primary_bool"]
}

def _format_schema_for_prompt() -> str:
    """Format database schema for LLM prompt."""
    schema_str = "DATABASE SCHEMA:\n"
    assert 'tables' in database_schema and isinstance(database_schema['tables'], dict), "database_schema['tables'] must be a dict"
    for table_name, table_info in database_schema['tables'].items():
        assert isinstance(table_info, dict), f"Table '{table_name}' info must be a dict, got {type(table_info)}"
        assert 'columns' in table_info and isinstance(table_info['columns'], dict), f"Table '{table_name}' must have 'columns' as dict"
        schema_str += f"{table_name} table:\n"
        for col_name, col_info in table_info['columns'].items():
            assert isinstance(col_info, dict), f"Column '{col_name}' in table '{table_name}' must be a dict, got {type(col_info)}"
            col_type = col_info['type']
            if 'example' in col_info:
                schema_str += f"  - {col_name} ({col_type}, e.g. '{col_info['example']}')\n"
            else:
                schema_str += f"  - {col_name} ({col_type})\n"
        schema_str += "\n"
    return schema_str

def _format_missing_columns(item: dict) -> str:
    assert isinstance(item, dict), f"_format_missing_columns expects dict, got {type(item)}"
    if 'table' not in item or 'missing_columns' not in item:
        return ""
    info_str = f"1. The {item['table']} table does NOT have these columns:\n"
    for col in item['missing_columns']:
        info_str += f"   - NO '{col}' column\n"
    return info_str

def _format_active_vehicles_pattern(item: dict) -> str:
    assert isinstance(item, dict), f"_format_active_vehicles_pattern expects dict, got {type(item)}"
    if 'active_vehicles_pattern' not in item:
        return ""
    return (
        "\n2. For 'active' vehicles:\n"
        "   - A vehicle is considered 'active' if it has trips in the current month\n"
        "   - Use this pattern: " + item['active_vehicles_pattern'] + "\n"
    )

def _format_last_active_date_pattern(item: dict) -> str:
    assert isinstance(item, dict), f"_format_last_active_date_pattern expects dict, got {type(item)}"
    if 'last_active_date_pattern' not in item:
        return ""
    return (
        "\n3. For 'last active date':\n"
        f"   - Use: {item['last_active_date_pattern']}\n"
    )

def _format_date_functions(item: dict) -> str:
    assert isinstance(item, dict), f"_format_date_functions expects dict, got {type(item)}"
    if 'date_functions' not in item or not isinstance(item['date_functions'], dict):
        return ""
    info_str = "\n4. Use PostgreSQL date functions, NOT MySQL functions:\n"
    for func_name, func_pattern in item['date_functions'].items():
        if func_name != 'forbidden':
            info_str += f"   * For '{func_name}': {func_pattern}\n"
    if 'forbidden' in item['date_functions']:
        info_str += f"   * Never use {', '.join(item['date_functions']['forbidden'])} syntax\n"
    return info_str

def _format_critical_info_for_prompt() -> str:
    assert 'critical_info' in database_schema and isinstance(database_schema['critical_info'], list), "database_schema['critical_info'] must be a list"
    info = database_schema['critical_info']
    info_str = "CRITICAL SCHEMA INFORMATION - READ CAREFULLY:\n"
    for item in info:
        assert isinstance(item, dict), f"Each item in critical_info must be a dict, got {type(item)}"
        info_str += _format_missing_columns(item)
        info_str += _format_active_vehicles_pattern(item)
        info_str += _format_last_active_date_pattern(item)
        info_str += _format_date_functions(item)
    return info_str

def _create_prompt_framework() -> str:
    """Create the BROKE framework for prompt generation."""
    return """### BROKE Framework for Prompt
#### 1. Background
This prompt is for translating natural language questions into executable SQL queries.
It uses `semantic_mapping.yaml` and `domain_glossary.py` to help the LLM identify correct tables and columns.

#### 2. Role
You are an SQL expert: interpret user intent, select valid schema components, avoid hallucinated tables/columns, and generate correct SQL.
Your expertise includes:
- Understanding fleet management domain concepts
- Writing efficient PostgreSQL queries
- Using correct table aliases and joins
- Handling date/time operations properly
- Ensuring data security with fleet_id filtering

#### 3. Objectives
- Generate valid SQL from user questions
- Use correct schema components and relationships
- Handle common errors like misnamed columns
- Ensure proper table joins and filtering
- Maintain query performance and security

#### 4. Key Results
- SQL queries reference only known tables and columns
- Uses aliases and filters based on semantic mapping
- Properly handles date ranges and aggregations
- Includes necessary security filters
- Returns results in a consistent format

#### 5. Evolve
- Update mappings as schema changes
- Expand glossary for domain-specific terms
- Improve handling of complex queries
- Better error detection and correction
- Enhanced performance optimization"""

def _create_sql_generation_prompt() -> str:
    """Create the system prompt for SQL generation, used by all LLM providers."""
    return f"""{_create_prompt_framework()}

You are a SQL expert for a fleet management system. 
            Generate PostgreSQL queries based on natural language questions.
            
            Your responsibilities:
            1. Understand user intent and convert to SQL
            2. Use correct table and column names from schema
            3. Write proper JOIN conditions
            4. Apply appropriate WHERE filters
            5. Handle aggregations and grouping
            6. Use correct table aliases
            7. Generate syntactically valid PostgreSQL SQL
            8. Use correct data types and operators
            9. ALWAYS include WHERE fleet_id = :fleet_id for security
            
            DO NOT handle:
            1. LIMIT clauses (we will add them)
            2. Error handling and fallbacks (we will manage it)
            
            Only use SELECT statements, never INSERT, UPDATE, DELETE, etc.
            Do not use SQL comments in your queries.
            Return the SQL query without any explanation or formatting.
            You must generate a valid PostgreSQL SELECT query.
            
            SQL Formatting Guidelines:
            1. Put each major clause on a new line (SELECT, FROM, WHERE, GROUP BY, ORDER BY)
            2. Indent sub-clauses and conditions
            3. Align JOIN conditions
            4. Use consistent spacing around operators
            5. Keep line length reasonable (around 80-100 characters)
            
{_format_schema_for_prompt()}

{_format_critical_info_for_prompt()}

Important rules for table and column usage:
1. Always use the exact table names from the schema
2. Always use the exact column names from the schema
3. For energy consumption, use trips.energy_kwh
4. For trip distance, use trips.distance_km
5. For vehicle information, join with vehicles table
6. For time-based queries, use trips.start_ts and trips.end_ts
7. Never use non-existent tables like 'vehicle_energy_usage'
8. Always qualify column names with table aliases (e.g., v.vehicle_id, t.energy_kwh)
9. ALWAYS include WHERE fleet_id = :fleet_id in your query for security
            
            Important: You must return the SQL query in the 'sql' parameter of the function call.
            Do NOT return the query in the 'query' parameter or any other parameter.
            Do NOT include vehicle IDs in the fleet_id parameter - use them in the SQL WHERE clause.
            
            When interpreting the user query, use the domain glossary provided to understand 
            fleet-specific terminology and data model relationships."""

def _parse_openai_function_args(function_call) -> dict:
    """Parse and validate OpenAI function call arguments."""
    if not function_call:
        print("OpenAI response missing function call")
        raise ValueError("OpenAI response missing function call structure")
        
    try:
        return json.loads(function_call.arguments)
    except json.JSONDecodeError as e:
        print(f"Failed to decode OpenAI function arguments: {str(e)}")
        print(f"Raw arguments received: {function_call.arguments}")
        raise ValueError(f"Invalid function arguments from OpenAI: {str(e)}")

def _extract_sql_from_openai_response(function_args: dict) -> str:
    """Extract SQL from OpenAI function arguments, with fallback logic."""
    sql = function_args.get("sql", "")
    
    # If SQL is empty, try to find it elsewhere in the response
    if not sql:
        # Check if there's a query field that might contain SQL instead
        potential_sql = function_args.get("query", "")
        if potential_sql and "SELECT" in potential_sql.upper():
            print(f"OpenAI returned SQL in query field instead of sql field: {potential_sql}")
            return potential_sql
        
        # Check if we have other content that looks like SQL
        for key, value in function_args.items():
            if isinstance(value, str) and "SELECT" in value.upper():
                print(f"Found potential SQL in {key} field: {value}")
                return value
    
    if not sql:
        print(f"OpenAI returned empty SQL - function args: {function_args}")
        raise ValueError("OpenAI returned empty SQL in response")
        
    return sql

def _build_sql_prompt(query: str) -> str:
    """Builds the full prompt for SQL generation, with BROKE at the top."""
    mapping_table, _ = get_semantic_mapping_prompt()
    glossary_str = glossary_to_string(DOMAIN_GLOSSARY, include_why_it_matters=True)
    anti_pattern = (
        "[Common mistakes and reasons]\n"
        "- Mistake: Using the 'last_active_date' column (this column does not exist in the schema and cannot be used to determine activity)\n"
        "- Mistake: Using 'status = 'active'' to determine activity (this column does not exist)\n"
        "-- Incorrect SQL example (do NOT generate this SQL):\n"
        "SELECT COUNT(*) FROM vehicles WHERE last_active_date >= date_trunc('month', CURRENT_DATE)  -- Incorrect, column does not exist\n"
    )
    example_block = (
        "[Examples]\n"
        "-- GOOD\n"
        "SQL: SELECT v.vehicle_id, SUM(t.energy_kwh) AS total_energy\n"
        "FROM vehicles v JOIN trips t ON v.vehicle_id = t.vehicle_id\n"
        "WHERE v.fleet_id = :fleet_id\n"
        "AND t.start_ts >= '2025-05-01' AND t.start_ts < '2025-06-01'\n"
        "GROUP BY v.vehicle_id\n"
        "ORDER BY total_energy DESC\n"
        "LIMIT 3;\n\n"
        "-- BAD\n"
        "SQL: SELECT * FROM vehicle_energy_usage -- ❌ Table does not exist\n"
    )
    requirements = (
        "[Requirements/Output Format]\n"
        "1. Always include 'WHERE fleet_id = :fleet_id' in your query for security\n"
        "2. Always include 'LIMIT 5000' at the end of your query\n"
        "3. Only use SELECT statements, never INSERT, UPDATE, DELETE, etc.\n"
        "4. Do not use SQL comments in your query\n"
        "5. Return only the SQL query, nothing else - no explanations, no formatting tags\n"
        "6. YOU MUST GENERATE A VALID PostgreSQL QUERY that starts with SELECT \n"
        "7. DO NOT return an empty response\n"
        "8. Use the domain glossary and semantic mapping provided above to understand fleet-specific terminology and tables\n"
    )
    return f"""{_create_prompt_framework()}

User question: {query}

[Semantic Mapping]\n{mapping_table}\n\n[Domain Glossary]\n{glossary_str}\n\n[Critical Info]\n{_format_critical_info_for_prompt()}\n\n[Schema]\n{_format_schema_for_prompt()}\n\n{anti_pattern}\n\n{example_block}\n\n{requirements}\n"""

def _build_answer_prompt(query: str, sql_result: dict) -> str:
    """Builds the full prompt for answer explanation, with BROKE at the top."""
    glossary_str = glossary_to_string(DOMAIN_GLOSSARY)
    business_rules_str = "\n".join(BUSINESS_RULES['rules'])
    try:
        context_str = json.dumps(sql_result, default=str, indent=2)
    except Exception:
        context_str = str(sql_result)
    hallucination_reminder = (
        "\n\n[Reminder to LLM: Only use columns and tables defined in the schema. "
        "If the SQL result is empty or contains errors, analyze the reason and provide a helpful explanation to the user. "
        "Suggest how they might rephrase their question to get the information they need.]"
        "\n\nGiven the above context, analyze the SQL and its result. If there is an error, explain the likely cause in plain language, referencing the Domain Glossary and Business Rules as needed. Suggest how the user could rephrase or clarify their question to get a better answer."
    )
    return (
        f"{_create_prompt_framework()}\n"
        f"User question: {query}\n"
        f"\nDomain Glossary:\n{glossary_str}\n"
        f"\nBusiness Rules:\n{business_rules_str}\n"
        f"\nContext:\n{context_str}"
        f"{hallucination_reminder}"
    )

def _correct_invalid_columns(sql: str) -> str:
    """
    Correct common invalid column references in SQL queries.
    Args:
        sql: SQL query string
    Returns:
        Corrected SQL query string
    """
    # Example correction: Replace 'trips.energy' with 'trips.energy_kwh' in 'trips' table
    corrected_sql = sql.replace(TRIPS_ENERGY, TRIPS_ENERGY_KWH)
    return corrected_sql

def _prepare_result_context(query: str, sql: str, sql_result: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare context for LLM based on query result type."""
    if sql_result.get("is_empty_result", False):
        return {
            "query": query,
            "sql": sql,
            "row_count": 0,
            "query_context": sql_result.get("query_context", {}),
            "message": sql_result.get("message", ""),
            "is_empty_result": True
        }
    
    return {
        "query": query,
        "sql": sql,
        "row_count": len(sql_result.get("rows", [])),
        "rows": sql_result.get("rows", [])[:10],
        "is_empty_result": False
    }

async def _handle_empty_result(query: str, sql: str, sql_result: Dict[str, Any]) -> Dict[str, Any]:
    """Handle case when query returns no results."""
    fleet_id = sql_result.get("query_context", {}).get("fleet_id")
    if not fleet_id:
        return _prepare_result_context(query, sql, sql_result)
    
    fallback_result = await _try_fallback_query(query, sql, fleet_id)
    if not fallback_result:
        return _prepare_result_context(query, sql, sql_result)
    
    # Use fallback results
    context = _prepare_result_context(query, sql, fallback_result)
    context["is_fallback"] = True
    context["fallback_message"] = "I couldn't find specific data for your query, but here's some general information from the same table:"
    return context

async def _try_fallback_query(query: str, sql: str, fleet_id: int) -> Dict[str, Any]:
    """Try a more generic query when specific query returns no results."""
    print("No results found with specific query. Trying fallback query...")
    
    # Extract the base table from the original SQL
    base_table = None
    if "FROM" in sql.upper():
        from_match = re.search(r'FROM\s+([a-z_]+)', sql, re.IGNORECASE)
        if from_match:
            base_table = from_match.group(1)
    
    if not base_table:
        return None
        
    # Create a more generic query
    fallback_sql = f"""
    SELECT * FROM {base_table}
    WHERE fleet_id = :fleet_id
    LIMIT 10
    """
    
    try:
        async with engine.connect() as conn:
            await setup_database_session(conn, fleet_id)
            rows, error = await execute_sql_query(conn, fallback_sql, {"fleet_id": fleet_id})
            
            if error or not rows:
                return None
                
            return {
                "rows": rows,
                "row_count": len(rows),
                "is_fallback": True,
                "original_query": query,
                "original_sql": sql,
                "fallback_sql": fallback_sql
            }
    except Exception:
        return None

async def _safe_llm_response(context: str, providers: Dict[str, str]) -> str:
    """Get response from the configured LLM provider."""
    provider = get_llm_provider()
    api_key = providers.get(provider)
    
    if not api_key or not api_key.strip():
        return _generate_fallback_response(context)
        
    try:
        return await llm_answer_format(context, provider)
    except Exception as e:
        print(f"Error with {provider}: {str(e)}")
        return _generate_fallback_response(context)

def _generate_fallback_response(context: str) -> str:
    """Generate a fallback response when LLM is unavailable."""
    try:
        context_dict = json.loads(context)
        query = context_dict.get("query", "")
        error = context_dict.get("error", "")
        sql = context_dict.get("sql", "")
        
        if error:
            return (
                f"I understand you're asking about {query}. "
                f"While I couldn't process this specific query, I can help you rephrase it. "
                f"Based on the error, it seems there might be an issue with how the data is being accessed. "
                f"Could you try asking your question in a different way? For example, you could:"
                f"\n1. Break down your question into simpler parts"
                f"\n2. Use more general terms from our domain glossary"
                f"\n3. Focus on specific metrics or time periods"
            )
        elif not sql:
            return (
                f"I understand you're asking about {query}. "
                f"While I couldn't generate a specific query for this question, I can help you get the information you need. "
                f"Could you try:"
                f"\n1. Using more specific terms from our domain glossary"
                f"\n2. Breaking down your question into smaller parts"
                f"\n3. Focusing on specific metrics or time periods"
            )
        else:
            return (
                f"I understand you're asking about {query}. "
                f"While I'm having trouble processing this specific query right now, I can help you get the information you need. "
                f"Could you try rephrasing your question using terms from our domain glossary? "
                f"For example, you could ask about specific metrics like energy consumption, trip distance, or vehicle status."
            )
    except Exception as e:
        print(f"Error in fallback response generation: {str(e)}")
        return TROUBLE_MSG

async def generate_with_constraints(query: str, sql_result: Dict[str, Any], sql: str, strategy: str = "base", fleet_id: int = None) -> str:
    """
    Generate responses using different strategies.
    
    Args:
        query: Original natural language query
        sql_result: Result from sql_exec
        sql: SQL query that was executed
        strategy: Response generation strategy ("base", "strict", "cite")
        fleet_id: Fleet ID for filtering
        
    Returns:
        Human-readable answer formatted according to the specified strategy
    """
    try:
        print(f"[generate_with_constraints] Using strategy: {strategy}")
        
        if strategy == "base":
            # Use the existing answer_format function for base strategy
            return await answer_format(query, sql_result, sql, fleet_id=fleet_id)
        
        elif strategy == "strict":
            # Strict strategy: More formal, precise language with data validation
            return await _generate_strict_response(query, sql_result, sql, fleet_id=fleet_id)
        
        elif strategy == "cite":
            # Cite strategy: Include data sources and confidence indicators
            return await _generate_cited_response(query, sql_result, sql, fleet_id=fleet_id)
        
        else:
            print(f"[generate_with_constraints] Unknown strategy '{strategy}', falling back to base")
            return await answer_format(query, sql_result, sql, fleet_id=fleet_id)
            
    except Exception as e:
        print(f"Error in generate_with_constraints: {str(e)}")
        # Fallback to base strategy
        return await answer_format(query, sql_result, sql, fleet_id=fleet_id)

async def _generate_strict_response(query: str, sql_result: Dict[str, Any], sql: str, fleet_id: int = None) -> str:
    """Generate a strict, formal response with precise language."""
    try:
        # Prepare context similar to answer_format but with strict formatting
        if sql_result.get("is_empty_result", False) or not sql_result.get("rows"):
            context = await _handle_empty_result(query, sql, sql_result)
        else:
            context = _prepare_result_context(query, sql, sql_result)
        
        OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY, DEEPSEEK_API_KEY = check_llm_api_keys()
        providers = {
            "openai": OPENAI_API_KEY,
            "anthropic": ANTHROPIC_API_KEY,
            "mistral": MISTRAL_API_KEY,
            "deepseek": DEEPSEEK_API_KEY
        }
        
        # Create strict context with specific instructions
        strict_context = await _safe_context_preparation(query, context, sql)
        strict_context += "\n\nSTRICT MODE: Use formal, precise language. Include exact numbers. Avoid casual expressions. State limitations clearly."
        
        answer = await _safe_llm_response(strict_context, providers)
        if fleet_id is not None:
            answer = answer.replace(FLEET_ID_PLACEHOLDER, str(fleet_id))
        return answer
        
    except Exception as e:
        print(f"Error in _generate_strict_response: {str(e)}")
        return await answer_format(query, sql_result, sql, fleet_id=fleet_id)

async def _generate_cited_response(query: str, sql_result: Dict[str, Any], sql: str, fleet_id: int = None) -> str:
    """Generate a response with citations and confidence indicators."""
    try:
        # Prepare context similar to answer_format but with citation formatting
        if sql_result.get("is_empty_result", False) or not sql_result.get("rows"):
            context = await _handle_empty_result(query, sql, sql_result)
        else:
            context = _prepare_result_context(query, sql, sql_result)
        
        OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY, DEEPSEEK_API_KEY = check_llm_api_keys()
        providers = {
            "openai": OPENAI_API_KEY,
            "anthropic": ANTHROPIC_API_KEY,
            "mistral": MISTRAL_API_KEY,
            "deepseek": DEEPSEEK_API_KEY
        }
        
        # Create cited context with specific instructions
        cited_context = await _safe_context_preparation(query, context, sql)
        cited_context += "\n\nCITATION MODE: Include data sources, timestamps, and confidence indicators. Reference specific tables/columns used. Add '[Source: table_name]' citations."
        
        answer = await _safe_llm_response(cited_context, providers)
        if fleet_id is not None:
            answer = answer.replace(FLEET_ID_PLACEHOLDER, str(fleet_id))
        return answer
        
    except Exception as e:
        print(f"Error in _generate_cited_response: {str(e)}")
        return await answer_format(query, sql_result, sql, fleet_id=fleet_id)

def _get_analysis_request(sql_result: dict) -> Optional[str]:
    if "error" in sql_result:
        if "syntax error" in sql_result["error"].lower():
            return (
                "The SQL query has a syntax error. Please explain the error in plain language "
                "and provide the corrected SQL query. Do not suggest rephrasing the question "
                "unless the syntax error cannot be fixed."
            )
        else:
            return (
                "Please analyze why this SQL query failed and provide a helpful explanation to the user. "
                "Focus on suggesting how they might rephrase their question to get the information they need. "
                "Use the domain glossary to understand the business context."
            )
    return None

def _add_field_info_blocks(sql_result: dict) -> str:
    field_error_block = f"\nField Error: {sql_result['field_error']}\n" if 'field_error' in sql_result else ""
    invalid_fields_block = f"Invalid fields: {sql_result['invalid_fields']}\n" if 'invalid_fields' in sql_result else ""
    suggested_fields_block = f"Suggested valid fields: {sql_result['suggested_fields']}\n" if 'suggested_fields' in sql_result else ""
    return field_error_block + invalid_fields_block + suggested_fields_block

def _safe_context_serialize(context: dict, query: str, sql: str, row_count: int, is_fallback: bool) -> str:
    try:
        return json.dumps(context, default=str, indent=2)
    except Exception:
        context = {
            "query": query,
            "sql": sql,
            "row_count": row_count,
            "is_fallback": is_fallback,
            "error": "Error serializing full results",
            "analysis_request": (
                "Please analyze why this query failed and provide a helpful explanation to the user. "
                "Focus on suggesting how they might rephrase their question."
            )
        }
        return json.dumps(context, default=str, indent=2)

def _prepare_answer_context(query: str, sql_result: Dict[str, Any], sql: str, fleet_id: Optional[int] = None, fleet_name: Optional[str] = None) -> str:
    """
    Prepare context for answer formatting.
    """
    if not isinstance(sql_result, dict):
        sql_result = {"rows": [], "error": "Invalid SQL result format"}
    rows = sql_result.get("rows", [])
    row_count = sql_result.get("row_count", len(rows) if rows else 0)
    is_fallback = sql_result.get("is_fallback", False)
    context = {
        "query": query,
        "sql": sql,
        "row_count": row_count,
        "is_fallback": is_fallback
    }
    if fleet_id is not None:
        context["fleet_id"] = fleet_id
    if fleet_name is not None:
        context["fleet_name"] = fleet_name
    analysis_request = _get_analysis_request(sql_result)
    if analysis_request:
        context["analysis_request"] = analysis_request
    if "error" in sql_result:
        context["error"] = sql_result["error"]
    if rows:
        context["rows"] = rows[:10]
    elif "download_url" in sql_result:
        context["download_url"] = sql_result["download_url"]
    if "field_error" in sql_result:
        context["field_error"] = sql_result["field_error"]
    if "invalid_fields" in sql_result:
        context["invalid_fields"] = sql_result["invalid_fields"]
    if "suggested_fields" in sql_result:
        context["suggested_fields"] = sql_result["suggested_fields"]
    context_str = _safe_context_serialize(context, query, sql, row_count, is_fallback)
    glossary_str = glossary_to_string(DOMAIN_GLOSSARY)
    business_rules_str = "\n".join(BUSINESS_RULES['rules'])
    user_question_block = f"User question: {query}\n"
    field_info_blocks = _add_field_info_blocks(sql_result)
    hallucination_reminder = (
        "\n\nWhen explaining results or errors, use the Domain Glossary to clarify terms, and refer to the Business Rules to guide your suggestions."
        "\n\n[Reminder to LLM: Always mention the fleet_id (and fleet name if available) in your answer, so the user knows which fleet the data refers to. "
        "Only use columns and tables defined in the schema. If the SQL result is empty or contains errors, analyze the reason and provide a helpful explanation to the user. "
        "Suggest how they might rephrase their question to get the information they need.]"
        "\n\nGiven the above context, analyze the SQL and its result. If there is an error, explain the likely cause in plain language, referencing the Domain Glossary and Business Rules as needed. Suggest how the user could rephrase or clarify their question to get a better answer."
    )
    return (
        user_question_block +
        field_info_blocks +
        f"\nDomain Glossary:\n{glossary_str}\n" +
        f"\nBusiness Rules:\n{business_rules_str}\n" +
        f"\nContext:\n{context_str}" +
        hallucination_reminder
    )

async def _handle_column_error(error_message: str) -> str:
    """Handle column-related errors."""
    column_match = re.search(r'column ([\w.]+) does not exist', error_message, re.IGNORECASE)
    if not column_match:
        return f"I encountered an error: {error_message}. Please try again with a different question."
        
    bad_column = column_match.group(1)
    if "energy" in bad_column.lower() and "trips" in bad_column.lower():
        return f"I encountered an error with the column '{bad_column}'. In our database, the trips table has 'energy_kwh' instead of just 'energy'."
    
    return f"I encountered an error with the column '{bad_column}' which doesn't exist in our database."

def get_llm_provider() -> str:
    provider = os.getenv("LLM_PROVIDER")
    if provider:
        return provider.lower()
    # 自动检测可用的 API KEY
    if os.getenv("OPENAI_API_KEY", "").strip():
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    if os.getenv("MISTRAL_API_KEY", "").strip():
        return "mistral"
    if os.getenv("DEEPSEEK_API_KEY", "").strip():
        return "deepseek"
    raise RuntimeError("No LLM provider configured and no API key found.")

def glossary_to_string(glossary: dict, include_why_it_matters: bool = True) -> str:
    """
    Format the glossary as a readable string for LLM context.
    Args:
        glossary: The domain glossary dictionary
        include_why_it_matters: Whether to include the "Why it matters" field
    Returns:
        Formatted glossary as a string
    """
    lines = []
    for term, info in glossary.items():
        lines.append(f"{term}: {info['meaning']}")
        if include_why_it_matters and info.get("why_it_matters") and info["why_it_matters"]:
            lines.append(f"  Why it matters: {info['why_it_matters']}")
    return "\n".join(lines)

async def setup_database_session(conn, fleet_id: int) -> None:
    """
    Set up database session with timeouts and fleet ID.
    """
    await conn.execute(sa.text("SET statement_timeout = 20000"))
    fleet_id_sql = f"SET app.fleet_id = {fleet_id}"
    await conn.execute(sa.text(fleet_id_sql))

async def _llm_nl_to_sql(provider: str, query: str) -> Dict[str, str]:
    """Unified function to convert natural language to SQL using the specified LLM provider."""
    try:
        if provider == "openai":
            client = AsyncOpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                http_client=httpx.AsyncClient(timeout=60.0)
            )
            system_prompt = _create_sql_generation_prompt()
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prepare_sql_generation_context(query)}
                ],
                functions=[
                    {
                        "name": "generate_sql",
                        "description": "Generate a SQL query from natural language",
                        "parameters": GenerateSQLParameters.model_json_schema()
                    }
                ],
                function_call={"name": "generate_sql"},
                temperature=0.2
            )
            function_args = _parse_openai_function_args(response.choices[0].message.function_call)
            sql = _extract_sql_from_openai_response(function_args)
            return {"sql": sql, "prompt": system_prompt}
            
        elif provider == "anthropic":
            anthropic_client = anthropic.Anthropic(
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                timeout=60.0
            )
            prompt = f"""{_create_sql_generation_prompt()}

{prepare_sql_generation_context(query)}

SQL query:"""
    
            response = anthropic_client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            sql = response.content[0].text.strip()
            return {"sql": sql, "prompt": prompt}
            
        elif provider == "mistral":
            mistral_client = MistralClient(api_key=os.getenv("MISTRAL_API_KEY"))
            prompt = f"""{_create_sql_generation_prompt()}

{prepare_sql_generation_context(query)}

SQL query:"""
    
            response = mistral_client.chat(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            sql = response.choices[0].message.content.strip()
            return {"sql": sql, "prompt": prompt}
            
        elif provider == "deepseek":
            client = AsyncOpenAI(
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                base_url="https://api.deepseek.com/v1",
                http_client=httpx.AsyncClient(timeout=60.0)
            )
            prompt = f"""{_create_sql_generation_prompt()}

{prepare_sql_generation_context(query)}

SQL query:"""
            
            response = await client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            sql = response.choices[0].message.content.strip()
            return {"sql": sql, "prompt": prompt}
            
        else:
            raise ValueError(f"Unknown provider: {provider}")
            
    except Exception as e:
        print(f"Error in _llm_nl_to_sql with provider {provider}: {str(e)}")
        raise

async def llm_nl_to_sql(query: str) -> Dict[str, str]:
    """Convert natural language to SQL using the configured LLM provider."""
    provider = get_llm_provider()
    return await _llm_nl_to_sql(provider, query)

async def answer_format(query: str, sql_result: Dict[str, Any], sql: str, fleet_id: Optional[int] = None) -> str:
    """Format results into a human-readable answer using the configured LLM provider."""
    context = _prepare_answer_context(query, sql_result, sql, fleet_id=fleet_id)
    provider = get_llm_provider()
    answer = await llm_answer_format(context, provider)
    # Post-process: replace ':fleet_id' with the actual value if available
    if fleet_id is not None:
        answer = answer.replace(FLEET_ID_PLACEHOLDER, str(fleet_id))
    # Remove technical suggestions and SQL code blocks
    lines = answer.splitlines()
    filtered_lines = []
    in_code_block = False
    for line in lines:
        # Remove code blocks and lines with 'Suggested refinement' or 'Example:'
        if line.strip().startswith('```sql'):
            in_code_block = True
            continue
        if in_code_block:
            if line.strip().startswith('```'):
                in_code_block = False
            continue
        if 'Suggested refinement' in line or 'Example:' in line or 'query the' in line:
            continue
        filtered_lines.append(line)
    # Remove extra blank lines
    filtered_answer = '\n'.join([line for line in filtered_lines if line.strip()])
    # Append fleet_id at the bottom only if not already present
    if fleet_id is not None and str(fleet_id) not in filtered_answer:
        filtered_answer += f"\nFleet ID: {fleet_id}"
    return filtered_answer

async def _safe_context_preparation(query: str, context: Dict[str, Any], sql: str) -> str:
    """Prepare context for LLM in a safe manner."""
    try:
        return _prepare_answer_context(query, context, sql)
    except Exception as e:
        print(f"Error in _safe_context_preparation: {str(e)}")
        return f"User question: {query}\nSQL: {sql}\nError: {str(e)}"

async def llm_answer_format(context_str: str, provider: str) -> str:
    """Format results into a human-readable answer using the specified LLM provider."""
    prompt = f"""You are a fleet analytics assistant.
Given SQL query results, provide a concise, human-readable answer to the original question.
Respond in plain text only. Do not use Markdown, code blocks, or formatting tags. Use natural line breaks for clarity.
Be direct and informative. Include key numbers and insights. Keep your answer under 100 words.

The context contains a domain glossary with fleet management terms. Use these specialized terms appropriately in your response to sound more domain-aware.
When metrics like SOH (State of Health), SOC (State of Charge), or other domain-specific terms are involved, use the correct terminology and explain the results in fleet management context.

Here is the context including the domain glossary, query, SQL, and results:
{context_str}

Provide a concise answer to the original query based on these results:"""

    if provider == "openai":
        client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            http_client=httpx.AsyncClient(timeout=60.0)
        )
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip()
    elif provider == "anthropic":
        anthropic_client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            timeout=60.0
        )
        response = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    elif provider == "mistral":
        mistral_client = MistralClient(
            api_key=os.getenv("MISTRAL_API_KEY")
        )
        response = mistral_client.chat(
            model="mistral-small-latest",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    elif provider == "deepseek":
        client = AsyncOpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/v1",
            http_client=httpx.AsyncClient(timeout=60.0)
        )
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        return response.choices[0].message.content.strip()
    else:
        raise ValueError(f"Unknown provider: {provider}")

def prepare_sql_generation_context(query: str) -> str:
    """Prepare context for SQL generation including domain glossary and schema."""
    mapping_table, _ = get_semantic_mapping_prompt()
    glossary_str = glossary_to_string(DOMAIN_GLOSSARY, include_why_it_matters=True)
    return f"""User question: {query}

[Semantic Mapping]
{mapping_table}

[Domain Glossary]
{glossary_str}

[Critical Info]
{_format_critical_info_for_prompt()}

[Schema]
{_format_schema_for_prompt()}

Requirements:
1. Always include 'WHERE fleet_id = :fleet_id' in your query for security
2. Always include 'LIMIT 5000' at the end of your query
3. Only use SELECT statements, never INSERT, UPDATE, DELETE, etc.
4. Do not use SQL comments in your query
5. Return only the SQL query, nothing else - no explanations, no formatting tags
6. YOU MUST GENERATE A VALID PostgreSQL QUERY that starts with SELECT 
7. DO NOT return an empty response
8. Use the domain glossary provided above to understand fleet-specific terminology and tables"""

async def sql_exec(sql: str, fleet_id: int) -> Dict[str, Any]:
    """Execute SQL query with proper error handling and result formatting."""
    try:
        async with engine.connect() as conn:
            await setup_database_session(conn, fleet_id)
            rows, error = await execute_sql_query(conn, sql, {"fleet_id": fleet_id})
            
            if error:
                return {
                    "rows": [],
                    "error": error,
                    "is_empty_result": True
                }
                
            if not rows:
                return {
                    "rows": [],
                    "is_empty_result": True,
                    "query_context": {"fleet_id": fleet_id}
                }
                
            return {
                "rows": rows,
                "row_count": len(rows),
                "is_empty_result": False
            }
            
    except Exception as e:
        print(f"Error executing SQL: {str(e)}")
        return {
            "rows": [],
            "error": str(e),
            "is_empty_result": True
        }

async def process_query(query: str, fleet_id: int, strategy: str = "base") -> Dict[str, Any]:
    """
    Process a natural language query end-to-end with specified strategy.
    
    Args:
        query: Natural language query
        fleet_id: Fleet ID for filtering
        strategy: Query generation strategy ("base", "strict", or "cite")
    
    Returns:
        dict with keys: answer, sql, rows, download_url, is_fallback, prompt_sql, prompt_answer
    """
    print(f"[process_query] Processing query: '{query}' with strategy: '{strategy}'")
    try:
        sql_result = await llm_nl_to_sql(query)
        if not sql_result or "sql" not in sql_result:
            raise ValueError("Failed to generate SQL from query")
        sql = sql_result["sql"]
        exec_result = await sql_exec(sql, fleet_id)
        answer = await generate_with_constraints(query, exec_result, sql, strategy, fleet_id=fleet_id)
        return {
            "answer": answer,
            "sql": sql,
            "rows": exec_result.get("rows", []),
            "download_url": exec_result.get("download_url", None),
            "is_fallback": False,
            "prompt_sql": sql_result.get("prompt", ""),
            "prompt_answer": _prepare_answer_context(query, exec_result, sql, fleet_id=fleet_id)
        }
    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        print(f"[process_query] Error: {error_msg}")
        sql = sql if 'sql' in locals() else ""
        exec_result = exec_result if 'exec_result' in locals() else {"rows": [], "error": error_msg}
        try:
            answer = await answer_format(query, exec_result, sql, fleet_id=fleet_id)
        except Exception as e2:
            print(f"[process_query] LLM 2nd prompt also failed: {str(e2)}")
            answer = TROUBLE_MSG
        resp = {
            "answer": answer,
            "sql": sql,
            "rows": exec_result.get("rows", []),
            "download_url": exec_result.get("download_url", None),
            "is_fallback": True,
            "error": True,
            "error_details": error_msg,
            "prompt_sql": sql_result.get("prompt", "") if 'sql_result' in locals() else "",
            "prompt_answer": _prepare_answer_context(query, exec_result, sql, fleet_id=fleet_id) if 'exec_result' in locals() and 'sql' in locals() else ""
        }
        return resp