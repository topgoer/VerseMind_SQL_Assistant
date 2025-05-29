"""
Pipeline service for SQL Assistant.

This module provides the core functionality for:
1. Converting natural language to SQL
2. Executing SQL queries
3. Formatting results into human-readable answers
"""
import os
import uuid
import csv
import json
import re
import asyncio
from typing import Dict, List, Optional, Tuple, Any, Union
from datetime import datetime

import openai
import anthropic
from mistralai.client import MistralClient
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection
from fastapi import HTTPException
from openai import AsyncOpenAI

from sql_assistant.schemas.generate_sql import GenerateSQLParameters, GenerateSQLResponse
from sql_assistant.guardrails import validate_sql, validate_sql_with_extraction, extract_sql_query
from sql_assistant.services.domain_glossary import DOMAIN_GLOSSARY

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

def _check_llm_api_keys():
    """Check if at least one LLM API key is available."""
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
    MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
    
    if not any([OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY]):
        raise RuntimeError(
            "No LLM API key found. Please set at least one of: "
            "OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY"
        )
    
    return OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY

# Constants for error checking
EMPTY_SQL_ERROR = "empty sql"
BLANK_SQL_ERROR = "blank sql"

async def _try_llm_provider(provider_name, provider_fn, query, fleet_id):
    """Helper function to try an LLM provider and capture errors."""
    try:
        print(f"Attempting SQL generation with {provider_name}")
        return await provider_fn(query, fleet_id), None
    except Exception as e:
        error_msg = f"{provider_name} error: {str(e)}"
        print(error_msg)
        is_empty_error = (EMPTY_SQL_ERROR in str(e).lower() or BLANK_SQL_ERROR in str(e).lower())
        return None, (error_msg, is_empty_error)

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
        OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY = _check_llm_api_keys()
        
        # Try each available LLM in order, collecting errors for debugging
        errors = []
        empty_sql_errors = 0
        
        # Try OpenAI first if available
        if OPENAI_API_KEY:
            result, error_info = await _try_llm_provider("OpenAI", _openai_nl_to_sql, query, fleet_id)
            if result:
                return result
            elif error_info:
                errors.append(error_info[0])
                if error_info[1]:  # is empty error
                    empty_sql_errors += 1
                
        # Fall back to Anthropic if available
        if ANTHROPIC_API_KEY:
            result, error_info = await _try_llm_provider("Anthropic", _anthropic_nl_to_sql, query, fleet_id)
            if result:
                return result
            elif error_info:
                errors.append(error_info[0])
                if error_info[1]:  # is empty error
                    empty_sql_errors += 1
                
        # Fall back to Mistral if available
        if MISTRAL_API_KEY:
            result, error_info = await _try_llm_provider("Mistral", _mistral_nl_to_sql, query, fleet_id)
            if result:
                return result
            elif error_info:
                errors.append(error_info[0])
                if error_info[1]:  # is empty error
                    empty_sql_errors += 1
                
        # If we get here, all LLMs failed
        return _handle_llm_failures(errors, empty_sql_errors)
                
    except HTTPException:
        # Re-raise HTTP exceptions as is
        raise
    except Exception as e:
        print("Unexpected error in nl_to_sql: {}".format(str(e)))
        raise HTTPException(status_code=500, detail="Error generating SQL: {}".format(str(e)))

def _handle_llm_failures(errors, empty_sql_errors):
    """Handle the case where all LLM providers failed."""
    if not errors:
        raise HTTPException(status_code=500, detail="No LLM API key configured")
        
    error_summary = '; '.join(errors)
    
    # Provide more specific error message if all LLMs returned empty SQL
    if empty_sql_errors == len(errors) and empty_sql_errors > 0:
        print("All LLMs failed with empty SQL responses")
        # Try to generate a default SQL response
        try:
            default_sql = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100"
            extracted_sql = _validate_and_extract_sql(default_sql)
            print("Returning default SQL as fallback: {}".format(default_sql))
            return {"sql": extracted_sql, "is_fallback": True}
        except Exception as fallback_error:
            print("Even default SQL fallback failed: {}".format(str(fallback_error)))
            raise HTTPException(
                status_code=500,
                detail="Could not generate SQL from your query. All LLM models returned empty responses. Please try reformulating your question."
            )
    else:
        raise HTTPException(
            status_code=500,
            detail="All LLMs failed to generate SQL. Errors: {}".format(error_summary)
        )

def _check_sql_content(sql_text, error_message):
    """Helper function to check if SQL content is valid."""
    if not sql_text:
        print(error_message)
        raise ValueError(error_message)

def _is_valid_sql(sql_text):
    """Check if text contains valid SQL elements."""
    return "SELECT" in sql_text.upper()

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
    _check_sql_content(sql, "Null SQL response from LLM")
    _check_sql_content(sql.strip(), "Blank SQL response from LLM")
    
    print("Raw LLM output received for SQL extraction: {}{}".format(
        sql[:200], '...' if len(sql) > 200 else ''))
    
    # First try to extract the SQL part
    extracted_sql = extract_sql_query(sql)
    print("Extracted SQL: {}".format(extracted_sql))
    
    # Check if extraction resulted in something that looks like SQL
    if not extracted_sql or not _is_valid_sql(extracted_sql):
        print("SQL extraction failed to produce valid SQL")
        raise ValueError("Failed to extract valid SQL from LLM response")
    
    # Then validate it
    is_valid, error_message, validated_sql = validate_sql_with_extraction(sql)
    
    if not is_valid:
        print("SQL validation failed: {}".format(error_message))
        # Make one more attempt to extract SQL from quoted or formatted text
        contains_code_block = '```' in sql
        contains_select = "SELECT" in sql.upper()
        
        if contains_code_block or contains_select:
            print("Attempting more aggressive SQL extraction...")
            # Look for SELECT statement with more flexible pattern
            select_pattern = r"SELECT\s+.+?WHERE.+?fleet_id\s*=\s*:fleet_id.+?LIMIT\s+\d+"
            select_match = re.search(select_pattern, sql, re.IGNORECASE | re.DOTALL)
            if select_match:
                extracted_try2 = select_match.group(0)
                is_valid2, _ = validate_sql(extracted_try2)
                if is_valid2:
                    print("Second extraction attempt successful: {}".format(extracted_try2))
                    return extracted_try2
        
        raise ValueError("Generated SQL failed validation: {}".format(error_message))
    
    # Final check for empty or invalid SQL
    if not validated_sql or not _is_valid_sql(validated_sql):
        raise ValueError("Validation returned empty or invalid SQL")
    
    return validated_sql

async def _openai_nl_to_sql(query: str, fleet_id: int) -> Dict[str, str]:
    """Use OpenAI to convert natural language to SQL."""
    # Configure client at runtime
    # Import httpx for timeout configuration
    import httpx
    
    # Configure client with a longer timeout (60 seconds)
    # Use only supported parameters for the AsyncOpenAI client
    client = AsyncOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        http_client=httpx.AsyncClient(timeout=60.0)
    )
    
    try:
        # Prepare context with domain glossary
        context = prepare_sql_generation_context(query)
        print(f"Sending query to OpenAI: {query}")
        
        # Only use parameters supported by the OpenAI API
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": """You are a SQL expert for a fleet management system. 
                Generate PostgreSQL queries based on natural language questions.
                Always include 'WHERE fleet_id = :fleet_id' in your queries for security.
                Always include 'LIMIT 5000' at the end of your queries.
                Only use SELECT statements, never INSERT, UPDATE, DELETE, etc.
                Do not use SQL comments in your queries.
                Return the SQL query without any explanation or formatting.
                You must generate a valid PostgreSQL SELECT query.
                
                Important schema details:
                - The vehicles table does NOT have an 'active' column or 'last_active_date' column
                - To determine if a vehicle is "active" in a given month, use the trips table and check if there are trips in that month
                - For example: "active this month" means "there exists a trip in the trips table for this vehicle with start_ts in the current month"
                - Use EXTRACT(MONTH FROM start_ts) = EXTRACT(MONTH FROM CURRENT_DATE) to check current month activity
                - Use EXTRACT(YEAR FROM start_ts) = EXTRACT(YEAR FROM CURRENT_DATE) to ensure same year
                - Vehicle models are stored in the 'model' column of the vehicles table
                - For time-based queries, use the trips table with start_ts and end_ts columns
                - Use PostgreSQL date functions, NOT MySQL functions:
                  * For "last week": start_ts >= CURRENT_DATE - INTERVAL '7 days'
                  * For "this month": start_ts >= DATE_TRUNC('month', CURRENT_DATE)
                  * For "last month": start_ts >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month')
                  * Never use DATE_SUB(), CURDATE(), or INTERVAL x WEEK syntax
                
                Important: You must return the SQL query in the 'sql' parameter of the function call.
                Do NOT return the query in the 'query' parameter or any other parameter.
                Do NOT include vehicle IDs in the fleet_id parameter - use them in the SQL WHERE clause.
                
                When interpreting the user query, use the domain glossary provided to understand 
                fleet-specific terminology and data model relationships."""},
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
            temperature=0.2,  # Lower temperature for more deterministic SQL generation
            max_tokens=1000  # Ensure enough tokens for complete SQL
        )
        
        # Log the raw response for debugging
        print(f"OpenAI raw response: {str(response)[:500]}...")
        
        # Extract function call arguments
        function_call = response.choices[0].message.function_call
        if not function_call:
            print("OpenAI response missing function call - raw response content:", str(response))
            raise ValueError("OpenAI response missing function call structure")
            
        try:
            function_args = json.loads(function_call.arguments)
        except json.JSONDecodeError as e:
            print(f"Failed to decode OpenAI function arguments: {str(e)}")
            print(f"Raw arguments received: {function_call.arguments}")
            raise ValueError(f"Invalid function arguments from OpenAI: {str(e)}")
        
        # Extract and validate SQL
        sql = function_args.get("sql", "")
        
        # If SQL is empty, try to find it elsewhere in the response
        if not sql:
            # Check if there's a query field that might contain SQL instead
            potential_sql = function_args.get("query", "")
            if potential_sql and "SELECT" in potential_sql.upper():
                print(f"OpenAI returned SQL in query field instead of sql field: {potential_sql}")
                sql = potential_sql
            else:
                # Check if we have other content that looks like SQL
                for key, value in function_args.items():
                    if isinstance(value, str) and "SELECT" in value.upper():
                        print(f"Found potential SQL in {key} field: {value}")
                        sql = value
                        break
        
        if not sql:
            print(f"OpenAI returned empty SQL - function args: {function_args}")
            raise ValueError("OpenAI returned empty SQL in response")
            
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
        
        Important schema details:
        - The vehicles table does NOT have an 'active' column or 'last_active_date' column
        - To determine if a vehicle is "active" in a given month, use the trips table and check if there are trips in that month
        - For example: "active this month" means "there exists a trip in the trips table for this vehicle with start_ts in the current month"
        - Use EXTRACT(MONTH FROM start_ts) = EXTRACT(MONTH FROM CURRENT_DATE) to check current month activity
        - Use EXTRACT(YEAR FROM start_ts) = EXTRACT(YEAR FROM CURRENT_DATE) to ensure same year
        - Vehicle models are stored in the 'model' column of the vehicles table
        - For time-based queries, use the trips table with start_ts and end_ts columns
        - Use PostgreSQL date functions, NOT MySQL functions:
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
        
        Important schema details:
        - The vehicles table does NOT have an 'active' column or 'last_active_date' column
        - To determine if a vehicle is "active" in a given month, use the trips table and check if there are trips in that month
        - For example: "active this month" means "there exists a trip in the trips table for this vehicle with start_ts in the current month"
        - Use EXTRACT(MONTH FROM start_ts) = EXTRACT(MONTH FROM CURRENT_DATE) to check current month activity
        - Use EXTRACT(YEAR FROM start_ts) = EXTRACT(YEAR FROM CURRENT_DATE) to ensure same year
        - Vehicle models are stored in the 'model' column of the vehicles table
        - For time-based queries, use the trips table with start_ts and end_ts columns
        - Use PostgreSQL date functions, NOT MySQL functions:
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
    try:
        async with engine.connect() as conn:
            # Set statement timeout to 20 seconds (20000ms)
            await conn.execute(sa.text("SET statement_timeout = 20000"))
            
            # Set fleet_id for RLS - use direct string formatting for SET command
            # PostgreSQL doesn't support parameter binding for SET statements
            fleet_id_sql = f"SET app.fleet_id = {fleet_id}"
            await conn.execute(sa.text(fleet_id_sql))
            
            # Execute query with parameters
            result = await conn.execute(
                sa.text(sql),
                {"fleet_id": fleet_id}
            )
            
            # Fetch all rows
            rows = [dict(row) for row in result.mappings()]
            
            # Check if result is large (>100 rows)
            if len(rows) > 100:
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
            else:
                # Return rows directly
                return {"rows": rows}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing SQL: {str(e)}")

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
    rows = sql_result.get("rows", [])
    row_count = sql_result.get("row_count", len(rows) if rows else 0)
    is_fallback = sql_result.get("is_fallback", False)
    
    context = {
        "query": query,
        "sql": sql,
        "row_count": row_count,
        "is_fallback": is_fallback
    }
    
    if rows:
        context["rows"] = rows[:10]
    else:
        context["download_url"] = sql_result.get("download_url", "")
    
    context_str = json.dumps(context, default=str, indent=2)
    glossary_str = glossary_to_string(DOMAIN_GLOSSARY)
    return "Domain Glossary:\n{}\n\n{}".format(glossary_str, context_str)

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
        OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY = _check_llm_api_keys()
        full_context = _prepare_answer_context(query, sql_result, sql)
        
        if OPENAI_API_KEY:
            return await _openai_answer_format(full_context)
        elif ANTHROPIC_API_KEY:
            return await _anthropic_answer_format(full_context)
        elif MISTRAL_API_KEY:
            return await _mistral_answer_format(full_context)
        else:
            raise HTTPException(status_code=500, detail="No LLM API key configured")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error formatting answer: {str(e)}")

async def _openai_answer_format(context_str: str) -> str:
    """Use OpenAI to format results into a human-readable answer."""
    # Configure client at runtime
    import httpx
    
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
    context_with_fallback = {"is_fallback": is_fallback, **exec_result}
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
