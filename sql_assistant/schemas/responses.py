"""
API response schemas for VerseMind SQL Assistant.

This module defines the Pydantic models for API responses.
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class ChatResponse(BaseModel):
    """Response model for the /chat endpoint."""
    answer: str = Field(..., description="Natural language answer to the query")
    sql: str = Field(..., description="Generated SQL query")
    rows: Optional[List[Dict[str, Any]]] = Field(
        None, 
        description="Result rows (up to 100). Omitted for large result sets."
    )
    download_url: Optional[str] = Field(
        None, 
        description="URL to download CSV for result sets larger than 100 rows"
    )
    is_fallback: bool = Field(
        False,
        description="Indicates whether a fallback query was used due to LLM failure"
    )
