"""
LLM provider utilities for SQL Assistant.

This module handles interactions with different LLM providers.
"""
import os
from typing import Dict, Tuple, Any, Optional

from fastapi import HTTPException

# Constants for error checking
EMPTY_SQL_ERROR = "empty sql"
BLANK_SQL_ERROR = "blank sql"

def check_llm_api_keys():
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
            status_code=500,
            detail="All LLMs failed to generate SQL. Errors: {}".format(error_summary)
        )
