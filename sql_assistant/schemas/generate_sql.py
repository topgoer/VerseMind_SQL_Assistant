"""
Schemas for SQL generation function call.

This module defines the Pydantic models for the OpenAI function call to generate SQL.
"""
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class GenerateSQLParameters(BaseModel):
    """Parameters for the generate_sql function."""
    sql: str = Field(
        ..., 
        description="The generated SQL query that includes 'WHERE fleet_id = :fleet_id' and 'LIMIT 5000'"
    )

class GenerateSQLResponse(BaseModel):
    """Response from the generate_sql function."""
    sql: str = Field(
        ..., 
        description="The generated SQL query with fleet_id filter and LIMIT 5000"
    )
    explanation: Optional[str] = Field(
        None, 
        description="Optional explanation of the generated SQL"
    )
