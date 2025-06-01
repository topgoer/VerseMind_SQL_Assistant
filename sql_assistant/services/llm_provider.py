"""
LLM provider utilities for SQL Assistant.

This module handles interactions with different LLM providers.
"""
import os
from typing import Dict, Tuple, Optional
from dotenv import load_dotenv

from fastapi import HTTPException
import httpx

# Load environment variables from .env file
load_dotenv()

# Constants for error checking
EMPTY_SQL_ERROR = "empty sql"
BLANK_SQL_ERROR = "blank sql"

def check_llm_api_keys():
    """Check if at least one LLM API key is available."""
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    
    if not any([OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY, DEEPSEEK_API_KEY]):
        raise RuntimeError(
            "No LLM API key found. Please set at least one of: "
            "OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY, DEEPSEEK_API_KEY"
        )
    
    return OPENAI_API_KEY, ANTHROPIC_API_KEY, MISTRAL_API_KEY, DEEPSEEK_API_KEY

async def try_llm_provider(provider_name, provider_fn, query, fleet_id) -> Tuple[Optional[Dict[str, str]], Optional[Tuple[str, bool]]]:
    """Helper function to try an LLM provider and capture errors."""
    try:
        print(f"Attempting SQL generation with {provider_name}")
        result = await provider_fn(query, fleet_id)
        
        if not result or not result.get("sql"):
            print(f"{provider_name} returned empty or invalid result")
            return None, (f"{provider_name} returned empty SQL", True)
            
        return result, None
    except Exception as e:
        error_msg = f"{provider_name} error: {str(e)}"
        print(error_msg)
        is_empty_error = (EMPTY_SQL_ERROR in str(e).lower() or BLANK_SQL_ERROR in str(e).lower())
        return None, (error_msg, is_empty_error)

def handle_llm_failures(errors, empty_sql_errors, validate_and_extract_sql_fn):
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
            extracted_sql = validate_and_extract_sql_fn(default_sql)
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
            status_code=500,            detail="All LLMs failed to generate SQL. Errors: {}".format(error_summary)
        )

async def _deepseek_nl_to_sql(query: str, fleet_id: int) -> Dict[str, str]:
    """
    Use DeepSeek to convert natural language to SQL.
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is not set in environment variables.")

    # Construct DeepSeek API request
    url = "https://api.deepseek.com/v1/chat/completions"
    prompt = f"""You are a SQL expert for a fleet management system.
Generate PostgreSQL queries based on natural language questions.
Always include 'WHERE fleet_id = :fleet_id' in your queries for security.
Always include 'LIMIT 5000' at the end of your queries.
Only use SELECT statements, never INSERT, UPDATE, DELETE, etc.
Do not use SQL comments or markdown formatting in your queries.
Return ONLY the raw SQL query without any explanation, formatting, or markdown.
You must generate a valid PostgreSQL SELECT query.

Available tables and columns:
- vehicles: vehicle_id, model, last_active_date
- vehicle_energy_usage: vehicle_id, energy_consumed, timestamp
- trips: vehicle_id, distance_km, start_time, end_time

User Query: {query}"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-coder",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 512,
        "temperature": 0.2
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        # Clean returned SQL, remove possible markdown formatting
        sql = result["choices"][0]["message"]["content"].strip()
        sql = sql.replace("```sql", "").replace("```", "").strip()
        if not sql:
            raise ValueError("DeepSeek returned empty SQL text")
        return {"sql": sql}

# DeepSeek provider functions and logic can be added later
# For example:
# async def _deepseek_nl_to_sql(query: str, fleet_id: int) -> Dict[str, str]:
#     ...
