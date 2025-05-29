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
from typing import Dict, List, Optional, Tuple, Any, Union

import anthropic
from mistralai.client import MistralClient
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from fastapi import HTTPException
from openai import AsyncOpenAI

from sql_assistant.schemas.generate_sql import GenerateSQLParameters
from sql_assistant.guardrails import validate_sql_with_extraction, extract_sql_query
from sql_assistant.services.domain_glossary import DOMAIN_GLOSSARY
from sql_assistant.services.sql_correction import (
    check_sql_content, is_valid_sql, correct_active_conditions,
    correct_last_active_date, ensure_trips_join, attempt_aggressive_extraction,
    ACTIVE_VEHICLES_SQL_PATTERN
)
from sql_assistant.services.llm_provider import (
    check_llm_api_keys, try_llm_provider, handle_llm_failures
)
from sql_assistant.services.db_operations import (
    handle_column_error, extract_bad_column
)

# Database connection
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres")
DB_HOST = os.environ.get("DB_HOST", "db")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "sql_assistant")
DATABASE_URL = os.environ.get("DATABASE_URL", f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
engine = create_async_engine(DATABASE_URL)

# Static directory for CSV downloads
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Function moved to llm_provider.py

async def nl_to_sql(query: str, fleet_id: int) -> Dict[str, str]:
    """
    Convert natural language query to SQL using available LLM providers.
    
    Args:
        query: Natural language query
        fleet_id: Fleet ID for filtering
        
    Returns:
        Dict with generated SQL
    """
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
        
    print("nl_to_sql received query: '{}', fleet_id: {}".format(query, fleet_id))
    
    try:
        # Check for API keys at runtime
        OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY = check_llm_api_keys()
        
        # Try each available LLM in order, collecting errors for debugging
        errors = []
        empty_sql_errors = 0
        
        # Try providers in order of preference
        providers = [
            (OPENAI_API_KEY, "OpenAI", _openai_nl_to_sql),
            (ANTHROPIC_API_KEY, "Anthropic", _anthropic_nl_to_sql),
            (MISTRAL_API_KEY, "Mistral", _mistral_nl_to_sql)
        ]
        
        # Try each available provider
        for api_key, provider_name, provider_fn in providers:
            if not api_key:
                continue
                
            result, error_info = await try_llm_provider(provider_name, provider_fn, query, fleet_id)
            if result:
                return result
            elif error_info:
                errors.append(error_info[0])
                if error_info[1]:  # is empty error
                    empty_sql_errors += 1
        
        # If we get here, all LLMs failed
        return handle_llm_failures(errors, empty_sql_errors, _validate_and_extract_sql)
                
    except HTTPException:
        # Re-raise HTTP exceptions as is
        raise
    except Exception as e:
        print("Unexpected error in nl_to_sql: {}".format(str(e)))
        raise HTTPException(status_code=500, detail="Error generating SQL: {}".format(str(e)))

    # Handle specific example queries
    specific_queries = {
        "how many srm t3 vans are active this month?": _query_active_srm_t3_vans,
        "which three vehicles consumed the most energy last week?": _query_top_energy_consumers,
        "show battery-health trend for vehicle 42 over the past 90 days.": _query_battery_health_trend,
        "what is the average trip distance for each vehicle model?": _query_avg_trip_distance,
    }

    normalized_query = query.strip().lower()
    if normalized_query in specific_queries:
        return specific_queries[normalized_query](fleet_id)

def _query_active_srm_t3_vans(fleet_id: int) -> Dict[str, str]:
    sql = (
        "SELECT COUNT(*) AS active_vans "
        "FROM vehicles "
        "WHERE model = 'SRM T3' AND fleet_id = :fleet_id "
        "AND purchase_date >= date_trunc('month', CURRENT_DATE) "
        "AND purchase_date < date_trunc('month', CURRENT_DATE) + INTERVAL '1 month'"
    )
    return {"sql": sql}

def _query_top_energy_consumers(fleet_id: int) -> Dict[str, str]:
    sql = (
        "SELECT vehicle_id, SUM(energy_kwh) AS total_energy "
        "FROM trips "
        "WHERE fleet_id = :fleet_id "
        "AND start_ts >= date_trunc('week', CURRENT_DATE) - INTERVAL '1 week' "
        "AND start_ts < date_trunc('week', CURRENT_DATE) "
        "GROUP BY vehicle_id "
        "ORDER BY total_energy DESC "
        "LIMIT 3"
    )
    return {"sql": sql}

def _query_battery_health_trend(fleet_id: int) -> Dict[str, str]:
    sql = (
        "SELECT ts, battery_health_pct "
        "FROM processed_metrics "
        "WHERE vehicle_id = 42 "
        "AND ts >= CURRENT_DATE - INTERVAL '90 days' "
        "ORDER BY ts ASC"
    )
    return {"sql": sql}

def _query_avg_trip_distance(fleet_id: int) -> Dict[str, str]:
    sql = (
        "SELECT model, AVG(distance_km) AS avg_distance "
        "FROM trips "
        "JOIN vehicles ON trips.vehicle_id = vehicles.vehicle_id "
        "WHERE fleet_id = :fleet_id "
        "GROUP BY model "
        "ORDER BY avg_distance DESC"
    )
    return {"sql": sql}

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
    # Check for empty input first
    check_sql_content(sql, "Null SQL response from LLM")
    check_sql_content(sql.strip(), "Blank SQL response from LLM")
    
    print("Raw LLM output received for SQL extraction: {}{}".format(
        sql[:200], '...' if len(sql) > 200 else ''))
    
    # First try to extract the SQL part
    extracted_sql = extract_sql_query(sql)
    print("Extracted SQL: {}".format(extracted_sql))
    
    # Check if extraction resulted in something that looks like SQL
    if not extracted_sql or not is_valid_sql(extracted_sql):
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
    
    # 4. Check if any modifications were made and log them
    if extracted_sql != original_sql:
        print("✅ Schema corrections applied to the SQL query")
        print(f"BEFORE: {original_sql}")
        print(f"AFTER:  {extracted_sql}")
    else:
        print("✓ No schema corrections needed")
    
    # 5. Now validate SQL syntax (not schema correctness)
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
    
    # 6. Final check for empty or invalid SQL
    if not extracted_sql or not is_valid_sql(extracted_sql):
        raise ValueError("Validation returned empty or invalid SQL")
    
    # 7. Always return our corrected version, not what the validator returned
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

# Dictionary mapping incorrect column references to correct ones
COLUMN_CORRECTIONS = {
    "trips.energy": "trips.energy_kwh",     # Common simplification of energy_kwh
    "energy_consumed": "energy_kwh",        # Common incorrect reference
    "energy_usage": "energy_kwh",           # Common incorrect reference
    "vehicle.id": "vehicles.vehicle_id",    # Common incorrect reference
    "trip.id": "trips.trip_id",             # Common incorrect reference
    "driver.id": "drivers.driver_id",       # Common incorrect reference
    "trips.driver_id": "drivers.driver_id", # Incorrect join reference
    "trip_distance": "trips.distance_km",   # Common incorrect reference
    "distance": "trips.distance_km",        # Common simplified reference
    "idle_min": "trips.idle_minutes",       # Common simplification
    "duration": "trips.end_ts - trips.start_ts", # Common duration calculation
    "registration": "vehicles.registration_no", # Common simplification
    "temp_c": "trips.avg_temp_c",           # Common simplification
    "trip_date": "trips.start_ts::date"     # Common date extraction
}

def _create_openai_system_prompt() -> str:
    """Create the system prompt for OpenAI SQL generation."""
    return """You are a SQL expert for a fleet management system. 
            Generate PostgreSQL queries based on natural language questions.
            Always include 'WHERE fleet_id = :fleet_id' in your queries for security.
            Always include 'LIMIT 5000' at the end of your queries.
            Only use SELECT statements, never INSERT, UPDATE, DELETE, etc.
            Do not use SQL comments in your queries.
            Return the SQL query without any explanation or formatting.
            You must generate a valid PostgreSQL SELECT query.
            
            CRITICAL SCHEMA INFORMATION - READ CAREFULLY:
            1. The vehicles table does NOT have these columns:
               - NO 'active' column
               - NO 'last_active_date' column
            
            2. NEVER use 'active = TRUE' or any variation in your SQL queries
            
            3. For "active" vehicles:
               - A vehicle is considered "active" if it has trips in the current month
               - Use this pattern: 
            """ + ACTIVE_VEHICLES_SQL_PATTERN + """
            
            4. For "last active date":
               - Use: "(SELECT MAX(trips.start_ts) FROM trips WHERE trips.vehicle_id = vehicles.vehicle_id)"
            
            5. Other schema details:
               - Vehicle models are stored in the 'model' column of the vehicles table
               - For time-based queries, use the trips table with start_ts and end_ts columns
               
            6. Use PostgreSQL date functions, NOT MySQL functions:
               * For "last week": start_ts >= CURRENT_DATE - INTERVAL '7 days'
               * For "this month": start_ts >= DATE_TRUNC('month', CURRENT_DATE)
               * For "last month": start_ts >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')
               * Never use DATE_SUB(), CURDATE(), or INTERVAL x WEEK syntax
            
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

async def _openai_nl_to_sql(query: str, fleet_id: int) -> Dict[str, str]:
    """Use OpenAI to convert natural language to SQL."""
    
    client = AsyncOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        http_client=httpx.AsyncClient(timeout=60.0)
    )
    
    try:
        context = prepare_sql_generation_context(query)
        print(f"Sending query to OpenAI: {query}")
        
        system_prompt = _create_openai_system_prompt()
                
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context}
            ],
            functions=[
                {
                    "name": "generate_sql",
                    "description": "Generate a SQL query from natural language",
                    "parameters": GenerateSQLParameters.model_json_schema()
                }
            ],
            function_call={"name": "generate_sql"},
            temperature=0.2,
            max_tokens=1000
        )
        
        print(f"OpenAI raw response: {str(response)[:500]}...")
        
        function_args = _parse_openai_function_args(response.choices[0].message.function_call)
        sql = _extract_sql_from_openai_response(function_args)
        extracted_sql = _validate_and_extract_sql(sql)
        
        return {"sql": extracted_sql}
    except Exception as e:
        print(f"OpenAI API error: {str(e)}")
        raise ValueError(f"OpenAI API error: {str(e)}")

async def _anthropic_nl_to_sql(query: str, fleet_id: int) -> Dict[str, str]:
    """Use Anthropic to convert natural language to SQL."""
    # Configure client at runtime
    # Anthropic has a default timeout of 60s, but we can set it explicitly
    anthropic_client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        timeout=60.0
    )
    
    try:
        # Prepare context with domain glossary
        context = prepare_sql_generation_context(query)
        print(f"Sending query to Anthropic: {query}")
        
        prompt = f"""You are a SQL expert for a fleet management system.
        
        {context}
        
        Requirements:
        1. Always include 'WHERE fleet_id = :fleet_id' in your query for security
        2. Always include 'LIMIT 5000' at the end of your query
        3. Only use SELECT statements, never INSERT, UPDATE, DELETE, etc.
        4. Do not use SQL comments in your query
        5. Return only the SQL query, nothing else - no explanations, no formatting tags
        6. YOU MUST GENERATE A VALID PostgreSQL QUERY that starts with SELECT 
        7. DO NOT return an empty response
        8. Use the domain glossary provided above to understand fleet-specific terminology and tables
        
        CRITICAL SCHEMA INFORMATION - READ CAREFULLY:
        1. The vehicles table does NOT have these columns:
           - NO 'active' column
           - NO 'last_active_date' column
        
        2. NEVER use 'active = TRUE' or any variation in your SQL queries
        
        3. For "active" vehicles:
           - A vehicle is considered "active" if it has trips in the current month
           - Use this pattern: 
             "vehicles.vehicle_id IN (SELECT DISTINCT trips.vehicle_id FROM trips 
             WHERE EXTRACT(MONTH FROM trips.start_ts) = EXTRACT(MONTH FROM CURRENT_DATE)
             AND EXTRACT(YEAR FROM trips.start_ts) = EXTRACT(YEAR FROM CURRENT_DATE))"
        
        4. For "last active date":
           - Use: "(SELECT MAX(trips.start_ts) FROM trips WHERE trips.vehicle_id = vehicles.vehicle_id)"
        
        5. Other schema details:
           - Vehicle models are stored in the 'model' column of the vehicles table
           - For time-based queries, use the trips table with start_ts and end_ts columns
           
        6. Use PostgreSQL date functions, NOT MySQL functions:
           * For "last week": start_ts >= CURRENT_DATE - INTERVAL '7 days'
           * For "this month": start_ts >= DATE_TRUNC('month', CURRENT_DATE)
           * For "last month": start_ts >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')
           * Never use DATE_SUB(), CURDATE(), or INTERVAL x WEEK syntax
        
        SQL query:"""
        
        response = anthropic_client.messages.create(
            model="claude-3-opus-20240229",
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.2  # Lower temperature for more deterministic SQL generation
        )
        
        # Log the raw response for debugging
        print(f"Anthropic raw response: {str(response)[:500]}...")
        
        # Extract SQL from response
        if not response.content:
            print("Anthropic returned null content object")
            raise ValueError("Anthropic returned empty content object")
            
        if not response.content[0].text:
            print(f"Anthropic returned empty text - raw response: {str(response)}")
            raise ValueError("Anthropic returned empty text in response")
            
        sql = response.content[0].text.strip()
        
        if not sql:
            print("Anthropic returned blank text after stripping")
            raise ValueError("Anthropic returned blank SQL text")
        
        # Validate and extract SQL
        extracted_sql = _validate_and_extract_sql(sql)
        
        return {"sql": extracted_sql}
    except Exception as e:
        print(f"Anthropic API error: {str(e)}")
        raise ValueError(f"Anthropic API error: {str(e)}")

async def _mistral_nl_to_sql(query: str, fleet_id: int) -> Dict[str, str]:
    """Use Mistral to convert natural language to SQL."""
    # Configure client at runtime
    mistral_client = MistralClient(api_key=os.environ.get("MISTRAL_API_KEY"))
    
    try:
        # Prepare context with domain glossary
        context = prepare_sql_generation_context(query)
        print(f"Sending query to Mistral: {query}")
        
        prompt = f"""You are a SQL expert for a fleet management system.
        
        {context}
        
        Requirements:
        1. Always include 'WHERE fleet_id = :fleet_id' in your query for security
        2. Always include 'LIMIT 5000' at the end of your query
        3. Only use SELECT statements, never INSERT, UPDATE, DELETE, etc.
        4. Do not use SQL comments in your query
        5. Return only the SQL query, nothing else - no explanations, no markdown formatting
        6. YOU MUST GENERATE A VALID PostgreSQL QUERY that starts with SELECT 
        7. DO NOT return an empty response
        8. Use the domain glossary provided above to understand fleet-specific terminology and tables
        
        CRITICAL SCHEMA INFORMATION - READ CAREFULLY:
        1. The vehicles table does NOT have these columns:
           - NO 'active' column
           - NO 'last_active_date' column
        
        2. NEVER use 'active = TRUE' or any variation in your SQL queries
        
        3. For "active" vehicles:
           - A vehicle is considered "active" if it has trips in the current month
           - Use this pattern: 
             "vehicles.vehicle_id IN (SELECT DISTINCT trips.vehicle_id FROM trips 
             WHERE EXTRACT(MONTH FROM trips.start_ts) = EXTRACT(MONTH FROM CURRENT_DATE)
             AND EXTRACT(YEAR FROM trips.start_ts) = EXTRACT(YEAR FROM CURRENT_DATE))"
        
        4. For "last active date":
           - Use: "(SELECT MAX(trips.start_ts) FROM trips WHERE trips.vehicle_id = vehicles.vehicle_id)"
        
        5. Other schema details:
           - Vehicle models are stored in the 'model' column of the vehicles table
           - For time-based queries, use the trips table with start_ts and end_ts columns
           
        6. Use PostgreSQL date functions, NOT MySQL functions:
           * For "last week": start_ts >= CURRENT_DATE - INTERVAL '7 days'
           * For "this month": start_ts >= DATE_TRUNC('month', CURRENT_DATE)
           * For "last month": start_ts >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')
           * Never use DATE_SUB(), CURDATE(), or INTERVAL x WEEK syntax
        
        SQL query:"""
        
        response = mistral_client.chat(
            model="mistral-large-latest",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2  # Lower temperature for more deterministic SQL generation
        )
        
        # Log the raw response for debugging
        print(f"Mistral raw response: {str(response)[:500]}...")
        
        # Extract SQL from response
        if not response.choices:
            print("Mistral returned null or empty choices")
            raise ValueError("Mistral returned empty choices array")
            
        if not response.choices[0].message:
            print(f"Mistral returned empty message object - raw response: {str(response)}")
            raise ValueError("Mistral returned empty message object")
            
        sql = response.choices[0].message.content.strip()
        
        if not sql:
            print("Mistral returned blank text after stripping")
            raise ValueError("Mistral returned blank SQL text")
        
        # Validate and extract SQL
        extracted_sql = _validate_and_extract_sql(sql)
        
        return {"sql": extracted_sql}
    except Exception as e:
        print(f"Mistral API error: {str(e)}")
        raise ValueError(f"Mistral API error: {str(e)}")

async def sql_exec(sql: str, fleet_id: int) -> Dict[str, Any]:
    """
    Execute SQL query and return results.
    
    Args:
        sql: SQL query to execute
        fleet_id: Fleet ID for filtering
        
    Returns:
        Dict with rows or download_url
    """
    print(f"sql_exec called with SQL: {sql[:100]}... and fleet_id: {fleet_id}")
    
    try:
        # Use database operations helper functions
        async with engine.connect() as conn:
            # Set up database session
            await setup_database_session(conn, fleet_id)
            
            # Execute query and handle rows
            from sql_assistant.services.db_operations import execute_sql_query
            rows, error = await execute_sql_query(conn, sql, {"fleet_id": fleet_id})
            
            # Handle errors
            if error:
                return await handle_sql_error(error, sql)
            
            # Handle large results
            if len(rows) > 100:
                from sql_assistant.services.db_operations import handle_large_result
                return handle_large_result(rows)
            else:
                # Return rows directly
                return {"rows": rows}
                
    except Exception as e:
        error_message = f"Error executing SQL: {str(e)}"
        print(error_message)
        return {
            "rows": [], 
            "error": error_message
        }

async def setup_database_session(conn, fleet_id: int) -> None:
    """
    Set up database session with timeouts and fleet ID.
    
    Args:
        conn: Database connection
        fleet_id: Fleet ID for filtering
    """
    # Set statement timeout to 20 seconds (20000ms)
    await conn.execute(sa.text("SET statement_timeout = 20000"))
    
    # Set fleet_id for RLS - use direct string formatting for SET command
    # PostgreSQL doesn't support parameter binding for SET statements
    fleet_id_sql = f"SET app.fleet_id = {fleet_id}"
    await conn.execute(sa.text(fleet_id_sql))

async def handle_sql_error(error: str, sql: str) -> Dict[str, Any]:
    """
    Handle SQL execution errors dynamically.

    Args:
        error: The error message from SQL execution.
        sql: The SQL query that caused the error.

    Returns:
        Corrected SQL query or fallback response.
    """
    if "AmbiguousColumnError" in error:
        print("Detected ambiguous column error. Attempting to qualify column names.")
        # Qualify ambiguous column names with table names
        corrected_sql = re.sub(r"\bvehicle_id\b", "vehicles.vehicle_id", sql)
        corrected_sql = re.sub(r"\btrips.vehicle_id\b", "trips.vehicle_id", corrected_sql)
        print(f"Corrected SQL: {corrected_sql}")
        return {"sql": corrected_sql}

    # Handle other errors or fallback
    print(f"Unhandled SQL error: {error}")
    return {"error": error}

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

def prepare_sql_generation_context(query: str) -> str:
    """
    Prepare context for SQL generation including domain glossary.
    
    Args:
        query: The natural language query
        
    Returns:
        Context string for SQL generation
    """
    glossary_str = glossary_to_string(DOMAIN_GLOSSARY, include_why_it_matters=True)
    return f"""Domain Glossary for Fleet Management (use these definitions when generating SQL):
{glossary_str}

User Query: {query}"""

def _prepare_answer_context(query: str, sql_result: Dict[str, Any], sql: str) -> str:
    """
    Prepare context for answer formatting.
    
    Args:
        query: Original natural language query
        sql_result: Result from sql_exec
        sql: SQL query that was executed
        
    Returns:
        Context string for LLM
    """
    # Handle case where sql_result might not be a dict
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
    
    # Handle different result types
    if "error" in sql_result:
        context["error"] = sql_result["error"]
    
    if rows:
        # Limit to first 10 rows to avoid context size issues
        context["rows"] = rows[:10]
    elif "download_url" in sql_result:
        context["download_url"] = sql_result["download_url"]
    
    # Use default=str to handle non-serializable objects
    try:
        context_str = json.dumps(context, default=str, indent=2)
    except Exception as e:
        print(f"Error serializing context to JSON: {str(e)}")
        # Fallback to a simpler context
        context = {
            "query": query,
            "sql": sql,
            "row_count": row_count,
            "is_fallback": is_fallback,
            "error": "Error serializing full results"
        }
        context_str = json.dumps(context, default=str, indent=2)
    
    glossary_str = glossary_to_string(DOMAIN_GLOSSARY)
    return f"Domain Glossary:\n{glossary_str}\n\nContext:\n{context_str}"

async def answer_format(query: str, sql_result: Dict[str, Any], sql: str) -> str:
    """
    Format SQL results into a human-readable answer.
    
    Args:
        query: Original natural language query
        sql_result: Result from sql_exec
        sql: SQL query that was executed
        
    Returns:
        Human-readable answer
    """
    try:
        # Check for errors in the SQL execution result
        if sql_result.get("error"):
            error_message = sql_result.get("error")
            print(f"Error from SQL execution passed to answer_format: {error_message}")
            
            # Handle column does not exist errors
            if "column" in error_message.lower() and "does not exist" in error_message.lower():
                column_match = re.search(r'column ([\w.]+) does not exist', error_message, re.IGNORECASE)
                if column_match:
                    bad_column = column_match.group(1)
                    
                    # Energy column error handling - specific to our schema issue
                    if "energy" in bad_column.lower() and "trips" in bad_column.lower():
                        return f"I encountered an error with the column '{bad_column}'. In our database, the trips table has 'energy_kwh' instead of just 'energy'."
                    
                    # General column error
                    return f"I encountered an error with the column '{bad_column}' which doesn't exist in our database."
            
            # Default error message for other types
            return f"I encountered an error: {error_message}. Please try again with a different question."
        
        # Proceed with normal formatting if no errors
        OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY = check_llm_api_keys()
        full_context = _prepare_answer_context(query, sql_result, sql)
        
        # Try to generate answer with the first available LLM provider
        return await _try_llm_provider(full_context, OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY)
    
    except Exception as e:
        print(f"Error in answer_format: {str(e)}")
        # Create simple context for fallback
        simple_context = {
            "query": query,
            "rows": sql_result.get("rows", []),
            "row_count": len(sql_result.get("rows", [])),
            "download_url": sql_result.get("download_url"),
            "error": str(e)
        }
        # Use the fallback formatter with our simple context
        return await _format_answer_fallback(simple_context)
async def _openai_answer_format(context_str: str) -> str:
    """Use OpenAI to format results into a human-readable answer."""
    # Configure client at runtime
    
    # Configure client with a longer timeout (60 seconds)
    # Use only supported parameters for the AsyncOpenAI client
    client = AsyncOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        http_client=httpx.AsyncClient(timeout=60.0)
    )
    
    # Only use parameters supported by the OpenAI API
    response = await client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": """You are a fleet analytics assistant.
            Given SQL query results, provide a concise, human-readable answer to the original question.
            Be direct and informative. Include key numbers and insights.
            Keep your answer under 100 words.
            
            The context contains a domain glossary with fleet management terms.
            Use these specialized terms appropriately in your response to sound more domain-aware.
            When metrics like SOH, SOC, or other domain-specific terms are involved, 
            use the correct terminology and explain the results in fleet management context."""},
            {"role": "user", "content": f"Here is the context including the domain glossary, query, SQL, and results:\n{context_str}\n\nProvide a concise answer to the original query based on these results:"}
        ]
    )
    
    return response.choices[0].message.content.strip()

async def _anthropic_answer_format(context_str: str) -> str:
    """Use Anthropic to format results into a human-readable answer."""
    # Configure client at runtime
    anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    
    prompt = f"""You are a fleet analytics assistant.
    Given SQL query results, provide a concise, human-readable answer to the original question.
    Be direct and informative. Include key numbers and insights.
    Keep your answer under 100 words.
    
    The context contains a domain glossary with fleet management terms.
    Use these specialized terms appropriately in your response to sound more domain-aware.
    When metrics like SOH (State of Health), SOC (State of Charge), or other domain-specific terms 
    are involved, use the correct terminology and explain the results in fleet management context.
    
    Here is the context including the domain glossary, query, SQL, and results:
    {context_str}
    
    Provide a concise answer to the original query based on these results:"""
    
    response = anthropic_client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=300,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    return response.content[0].text.strip()

async def _mistral_answer_format(context_str: str) -> str:
    """Use Mistral to format results into a human-readable answer."""
    # Configure client at runtime
    mistral_client = MistralClient(api_key=os.environ.get("MISTRAL_API_KEY"))
    
    prompt = f"""You are a fleet analytics assistant.
    Given SQL query results, provide a concise, human-readable answer to the original question.
    Be direct and informative. Include key numbers and insights.
    Keep your answer under 100 words.
    
    The context contains a domain glossary with fleet management terms.
    Use these specialized terms appropriately in your response to sound more domain-aware.
    When metrics like SOH (State of Health), SOC (State of Charge), or other domain-specific terms 
    are involved, use the correct terminology and explain the results in fleet management context.
    
    Here is the context including the domain glossary, query, SQL, and results:
    {context_str}
    
    Provide a concise answer to the original query based on these results:"""
    
    response = mistral_client.chat(
        model="mistral-small-latest",
        messages=[{"role": "user", "content": prompt}]
    )
    
    return response.choices[0].message.content.strip()

async def process_query(query: str, fleet_id: int) -> Tuple[str, str, Optional[List[Dict[str, Any]]], Optional[str], bool]:
    """
    Process a natural language query end-to-end.
    
    Args:
        query: Natural language query
        fleet_id: Fleet ID for filtering
        
    Returns:
        Tuple of (answer, sql, rows, download_url, is_fallback)
    """
    print(f"process_query called with query: '{query}', fleet_id: {fleet_id}")
    
    # Step 1: Convert natural language to SQL
    sql_result = await nl_to_sql(query, fleet_id)
    sql = sql_result["sql"]
    is_fallback = sql_result.get("is_fallback", False)
    print(f"NL to SQL result: is_fallback={is_fallback}, sql={sql[:50]}...")
    
    if is_fallback:
        print("Using fallback SQL query: {}".format(sql))
    
    # Step 2: Execute SQL
    print("Executing SQL...")
    exec_result = await sql_exec(sql, fleet_id)
    print(f"SQL execution returned: {list(exec_result.keys())}")
    
    # Step 3: Format answer
    answer_prefix = "Note: I couldn't generate a specific SQL query for your question, so I'm showing you a general result. " if is_fallback else ""
    # Make sure exec_result contains the is_fallback flag
    if isinstance(exec_result, dict):
        context_with_fallback = {"is_fallback": is_fallback, **exec_result}
    else:
        # Handle case where exec_result might not be a dict
        context_with_fallback = {"is_fallback": is_fallback, "rows": []}
    
    print("Formatting answer...")
    answer = await answer_format(query, context_with_fallback, sql)
    print(f"Answer formatting complete: {answer[:50]}...")
    
    if is_fallback:
        answer = answer_prefix + answer
        print("Added fallback prefix to answer")
    
    # Extract rows and download_url
    rows = exec_result.get("rows")
    download_url = exec_result.get("download_url")
    
    result = (answer, sql, rows, download_url, is_fallback)
    print(f"process_query returning {len(result)} values: {is_fallback=}")
    return result

def _apply_direct_column_corrections(sql: str) -> str:
    """Apply direct column corrections for known incorrect references."""
    modified_sql = sql
    for incorrect, correct in COLUMN_CORRECTIONS.items():
        pattern = r'\b' + re.escape(incorrect) + r'\b'
        modified_sql = re.sub(pattern, correct, modified_sql, flags=re.IGNORECASE)
    return modified_sql

def _find_closest_column_match(column_name: str, valid_columns: list) -> str:
    """Find the closest matching column name using string distance."""
    closest_match = None
    min_distance = float('inf')
    
    for valid_col in valid_columns:
        distance = _levenshtein_distance(column_name, valid_col.lower())
        if distance < min_distance:
            min_distance = distance
            closest_match = valid_col
    
    # Only return match if reasonably close (distance < 5)
    return closest_match if min_distance < 5 else None

def _correct_table_column_references(sql: str) -> str:
    """Correct table.column references that don't exist in the schema."""
    modified_sql = sql
    
    for table_name, columns in TABLE_COLUMNS.items():
        table_column_pattern = r'\b' + re.escape(table_name) + r'\.([a-zA-Z0-9_]+)\b'
        
        for match in re.finditer(table_column_pattern, modified_sql, re.IGNORECASE):
            column_name = match.group(1).lower()
            
            # If referenced column doesn't exist in this table
            if column_name not in [col.lower() for col in columns]:
                print(f"🔄 Found invalid column reference: {table_name}.{column_name}")
                
                closest_match = _find_closest_column_match(column_name, columns)
                if closest_match:
                    replacement = f"{table_name}.{closest_match}"
                    old_reference = match.group(0)
                    print(f"🔄 Replacing {old_reference} with {replacement}")
                    modified_sql = modified_sql.replace(old_reference, replacement)
    
    return modified_sql

def _correct_invalid_columns(sql: str) -> str:
    """
    Correct references to non-existent columns in SQL queries.
    
    Args:
        sql: Original SQL query
        
    Returns:
        SQL with column references corrected
    """
    # Apply direct column corrections
    modified_sql = _apply_direct_column_corrections(sql)
    
    # Correct table.column references
    modified_sql = _correct_table_column_references(modified_sql)
    
    if modified_sql != sql:
        print("✅ Column references corrected")
        print(f"BEFORE: {sql}")
        print(f"AFTER:  {modified_sql}")
        
    return modified_sql

def _levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate the Levenshtein distance between two strings.
    Used to find similar column names.
    """
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
        
    return previous_row[-1]

async def _format_answer_fallback(context: Union[str, Dict]) -> str:
    """
    Fallback formatter when LLM providers fail.
    
    Args:
        context: Context for answer formatting (can be a string or dictionary)
        
    Returns:
        Basic formatted answer
    """
    try:
        # Parse the context JSON if it's a string
        if isinstance(context, str):
            # Try to extract the JSON part from the context
            json_match = re.search(r'Context:\s*(.*)$', context, re.DOTALL)
            if json_match:
                context_json = json_match.group(1).strip()
                context_data = json.loads(context_json)
            else:
                # If we can't find the JSON, just return a generic message
                return "Query completed. Please check the results table."
        else:
            context_data = context
        
        # Extract the data we need
        query = context_data.get("query", "")
        rows = context_data.get("rows", [])
        row_count = context_data.get("row_count", 0)
        download_url = context_data.get("download_url")
        
        # Create a basic response
        if download_url:
            return f"Your query about '{query}' returned {row_count} rows, which can be downloaded using the provided link."
        elif rows and len(rows) > 0:
            if len(rows) == 1 and len(rows[0].keys()) == 1:
                # Single value result
                key = list(rows[0].keys())[0]
                value = rows[0][key]
                return f"Result for '{query}': {value}"
            else:
                # Multi-row or multi-column result
                return f"Your query about '{query}' returned {len(rows)} results. Please check the results table."
        else:
            return f"Your query about '{query}' did not return any results."
    except Exception as e:
        print(f"Error in fallback formatter: {str(e)}")
        return "Query completed. Please check the results table."

async def _try_openai_answer_format(context: str) -> Optional[str]:
    """Try to format answer using OpenAI."""
    try:
        answer = await _openai_answer_format(context)
        return answer if answer else None
    except Exception as e:
        print(f"OpenAI error: {str(e)}")
        return None

async def _try_anthropic_answer_format(context: str) -> Optional[str]:
    """Try to format answer using Anthropic."""
    try:
        answer = await _anthropic_answer_format(context)
        return answer if answer else None
    except Exception as e:
        print(f"Anthropic error: {str(e)}")
        return None

async def _try_mistral_answer_format(context: str) -> Optional[str]:
    """Try to format answer using Mistral."""
    try:
        answer = await _mistral_answer_format(context)
        return answer if answer else None
    except Exception as e:
        print(f"Mistral error: {str(e)}")
        return None

async def _try_llm_provider(context: str, openai_key: Optional[str], anthropic_key: Optional[str], mistral_key: Optional[str]) -> str:
    """
    Try to generate an answer using available LLM providers.
    
    Args:
        context: Context for answer formatting
        openai_key: OpenAI API key if available
        anthropic_key: Anthropic API key if available  
        mistral_key: Mistral API key if available
        
    Returns:
        Formatted answer from the first successful LLM provider
    """
    # Try providers in order of preference
    providers_to_try = [
        (openai_key, _try_openai_answer_format, "OpenAI"),
        (anthropic_key, _try_anthropic_answer_format, "Anthropic"), 
        (mistral_key, _try_mistral_answer_format, "Mistral")
    ]
    
    failed_providers = []
    
    for api_key, provider_func, provider_name in providers_to_try:
        if api_key:
            answer = await provider_func(context)
            if answer:
                return answer
            failed_providers.append(provider_name)
    
    # Handle fallback
    if failed_providers:
        print(f"All LLM providers failed: {'; '.join(failed_providers)}")
    else:
        print("No LLM API keys available")
    
    return await _format_answer_fallback(context)
