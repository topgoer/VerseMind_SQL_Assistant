"""
Schemas for MCP (Model Context Protocol) envelope.

This module defines the Pydantic models for the MCP envelope and steps.
"""
from typing import Dict, List, Literal, Optional, Union, Any
from uuid import UUID
from pydantic import BaseModel

class Step(BaseModel):
    """
    Represents a single step in the MCP processing pipeline.
    
    Each step has a tool name, optional input, and optional output.
    """
    tool: Literal["llm_nl_to_sql", "sql_exec", "answer_format"]
    input: Optional[Union[Dict[str, Any], str]] = None
    output: Optional[Union[Dict[str, Any], str]] = None

class MCPEnvelope(BaseModel):
    """
    MCP envelope for request and response.
    
    Contains a trace ID, optional context, and a list of steps.
    """
    trace_id: UUID
    context: Optional[Dict[str, Any]] = None
    steps: List[Step]
