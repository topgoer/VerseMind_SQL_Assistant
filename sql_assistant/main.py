"""
Main application module for SQL Assistant.

This module defines the FastAPI application, routes, and middleware.
"""
import os
from typing import Dict
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from sql_assistant.auth import get_fleet_id, FleetMiddleware
from sql_assistant.schemas.responses import ChatResponse
from sql_assistant.schemas.mcp import MCPEnvelope, Step
from sql_assistant.services.pipeline import process_query, nl_to_sql, sql_exec, answer_format

# Get absolute path to static directory
STATIC_DIR = Path(__file__).parent.parent / "static"
CHAT_HTML_PATH = STATIC_DIR / "chat.html"

print(f"Static directory: {STATIC_DIR}")
print(f"Chat HTML path: {CHAT_HTML_PATH}")
print(f"Chat HTML exists: {CHAT_HTML_PATH.exists()}")

# Check if MCP is enabled
ENABLE_MCP = os.environ.get("ENABLE_MCP", "0").lower() in ("1", "true", "yes")

# Create FastAPI app
app = FastAPI(
    title="SQL Assistant",
    description="A natural language analytics layer for fleet operators",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add fleet middleware
app.add_middleware(FleetMiddleware)

# Custom middleware to suppress health check logs
@app.middleware("http")
async def silence_health_check_logs(request: Request, call_next):
    """
    Middleware that silences logs for health check requests.
    This prevents the frequent health check requests from cluttering the logs.
    """
    response = await call_next(request)
    
    # Check if this is a health check request to /ping
    if request.url.path == "/ping" and response.status_code == 200:
        # This effectively prevents uvicorn's access logger from logging this request
        # as it will see the status code as 0 which it skips
        response.status_code = 0
        # Reset to 200 right after to ensure the client still gets a proper status
        response.status_code = 200
    
    return response

# Mount static files directory
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
@app.get("/chat.html")
async def root():
    """Serve the chat interface."""
    if not CHAT_HTML_PATH.exists():
        raise HTTPException(status_code=500, detail=f"Chat HTML file not found at {CHAT_HTML_PATH}")
    return FileResponse(str(CHAT_HTML_PATH))

@app.get("/ping")
@app.head("/ping")
async def ping():
    """Health check endpoint. Supports both GET and HEAD methods.
    HEAD method is preferred for health checks as it's more lightweight."""
    return {"status": "ok"}

@app.post("/chat")
async def chat(
    request: Dict = Body(...),
    fleet_id: int = Depends(get_fleet_id)
):
    """
    Process a natural language query and return results.
    
    Args:
        request: Request body containing either 'query' or 'message' field
        fleet_id: Fleet ID from JWT token
        
    Returns:
        ChatResponse with answer, SQL, and results
    """
    try:
        # Accept either 'query' or 'message' field for compatibility
        query = request.get("query") or request.get("message")
        if not query:
            raise HTTPException(status_code=400, detail="Missing 'query' or 'message' field")
            
        print(f"Chat endpoint received query: '{query}', fleet_id: {fleet_id}")
        
        # Process query end-to-end
        print("Calling process_query...")
        result = await process_query(query, fleet_id)
        print(f"process_query returned {len(result)} values: {result[:2]}...")
        
        answer, sql, rows, download_url, is_fallback = result
        print(f"Unpacked values - is_fallback: {is_fallback}")
        
        # Return response
        response = ChatResponse(
            answer=answer,
            sql=sql,
            rows=rows,
            download_url=download_url,
            is_fallback=is_fallback
        )
        print(f"Created ChatResponse with is_fallback={is_fallback}")
        return response
    
    except Exception as e:
        print(f"Error in chat endpoint: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# MCP Helper functions
async def process_nl_to_sql_step(step: Step, query: str, fleet_id: int, envelope: MCPEnvelope) -> None:
    """
    Process a natural language to SQL step.
    
    Args:
        step: The step to process
        query: Natural language query
        fleet_id: Fleet ID from JWT token
        envelope: MCP envelope containing the step
    """
    try:
        step.output = await nl_to_sql(query, fleet_id)
    except Exception as e:
        # Provide helpful context about the error
        raise HTTPException(
            status_code=500,
            detail=f"Error in NL to SQL conversion: {str(e)}"
        )

async def get_or_create_sql_step(envelope: MCPEnvelope, current_step_index: int, query: str, fleet_id: int) -> Step:
    """
    Get existing SQL step or create and process a new one.
    
    Args:
        envelope: MCP envelope containing steps
        current_step_index: Index of the current step being processed
        query: Natural language query
        fleet_id: Fleet ID from JWT token
        
    Returns:
        The SQL step (either existing or newly created)
    """
    # Find existing SQL step
    sql_step = next((s for s in envelope.steps if s.tool == "nl_to_sql"), None)
    
    # Create and process a new SQL step if needed
    if not sql_step:
        sql_step = Step(tool="nl_to_sql")
        envelope.steps.insert(current_step_index, sql_step)
        await process_nl_to_sql_step(sql_step, query, fleet_id, envelope)
    elif not sql_step.output:
        # Process existing but incomplete SQL step
        await process_nl_to_sql_step(sql_step, query, fleet_id, envelope)
    
    return sql_step

async def process_sql_exec_step(step: Step, query: str, fleet_id: int, envelope: MCPEnvelope) -> None:
    """
    Process an SQL execution step.
    
    Args:
        step: The step to process
        query: Natural language query
        fleet_id: Fleet ID from JWT token
        envelope: MCP envelope containing the step
    """
    try:
        # Get or create SQL step first
        current_index = envelope.steps.index(step)
        sql_step = await get_or_create_sql_step(envelope, current_index, query, fleet_id)
        
        # Execute SQL
        sql = sql_step.output["sql"]
        step.output = await sql_exec(sql, fleet_id)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail="SQL step output is missing expected 'sql' field"
        )
    except Exception as e:
        # Provide helpful context about the error
        raise HTTPException(
            status_code=500,
            detail=f"Error executing SQL: {str(e)}"
        )

async def get_or_create_exec_step(envelope: MCPEnvelope, current_index: int, query: str, fleet_id: int) -> Step:
    """
    Get existing SQL execution step or create and process a new one.
    
    Args:
        envelope: MCP envelope containing steps
        current_index: Index of the current step being processed
        query: Natural language query
        fleet_id: Fleet ID from JWT token
        
    Returns:
        The SQL execution step (either existing or newly created)
    """
    # Find existing exec step
    exec_step = next((s for s in envelope.steps if s.tool == "sql_exec"), None)
    
    # Create and process a new exec step if needed
    if not exec_step:
        exec_step = Step(tool="sql_exec")
        envelope.steps.insert(current_index, exec_step)
        await process_sql_exec_step(exec_step, query, fleet_id, envelope)
    elif not exec_step.output:
        # Process existing but incomplete exec step
        await process_sql_exec_step(exec_step, query, fleet_id, envelope)
    
    return exec_step

async def process_answer_format_step(step: Step, query: str, fleet_id: int, envelope: MCPEnvelope) -> None:
    """
    Process an answer formatting step.
    
    Args:
        step: The step to process
        query: Natural language query
        fleet_id: Fleet ID from JWT token
        envelope: MCP envelope containing the step
    """
    try:
        # Get the current step index
        current_index = envelope.steps.index(step)
        
        # Get or create prerequisite steps
        sql_step = await get_or_create_sql_step(envelope, current_index, query, fleet_id)
        exec_step = await get_or_create_exec_step(envelope, current_index, query, fleet_id)
        
        # Check if this is a fallback query
        is_fallback = sql_step.output.get("is_fallback", False)
        
        # Add fallback info to the exec result
        context_with_fallback = {"is_fallback": is_fallback, **exec_step.output}
        
        # Format answer
        answer = await answer_format(
            query, 
            context_with_fallback, 
            sql_step.output["sql"]
        )
        
        # Add a prefix for fallback responses
        if is_fallback:
            answer_prefix = "Note: I couldn't generate a specific SQL query for your question, so I'm showing you a general result. "
            answer = answer_prefix + answer
            
        step.output = answer
    except KeyError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required field in step output: {str(e)}"
        )
    except Exception as e:
        # Provide helpful context about the error
        raise HTTPException(
            status_code=500,
            detail=f"Error formatting answer: {str(e)}"
        )

async def validate_mcp_envelope(envelope: MCPEnvelope) -> str:
    """Validate MCP envelope and extract query."""
    if not envelope.context or "query" not in envelope.context:
        raise HTTPException(
            status_code=400, 
            detail="Context must contain 'query' field"
        )
    
    return envelope.context["query"]

async def get_step_processor(tool_name: str) -> callable:
    """
    Get the appropriate processor function for a tool.
    
    Args:
        tool_name: Name of the tool to get processor for
        
    Returns:
        Processor function for the tool
        
    Raises:
        HTTPException: If tool is not supported
    """
    # Map of tool names to their processing functions
    step_processors = {
        "nl_to_sql": process_nl_to_sql_step,
        "sql_exec": process_sql_exec_step,
        "answer_format": process_answer_format_step
    }
    
    processor = step_processors.get(tool_name)
    if not processor:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported tool: {tool_name}"
        )
    
    return processor

async def process_pending_steps(envelope: MCPEnvelope, query: str, fleet_id: int) -> None:
    """
    Process all steps in the envelope that don't have output yet.
    
    Args:
        envelope: MCP envelope with steps to process
        query: Natural language query from context
        fleet_id: Fleet ID from JWT token
    """
    for step in envelope.steps:
        # Skip steps that already have output
        if step.output is not None:
            continue
            
        # Get processor and process the step
        processor = await get_step_processor(step.tool)
        await processor(step, query, fleet_id, envelope)

# Define MCP handler outside the conditional to simplify
async def handle_mcp_request(
    envelope: MCPEnvelope,
    fleet_id: int
) -> MCPEnvelope:
    """
    Process an MCP request envelope and return updated envelope with outputs.
    
    Args:
        envelope: MCP envelope with trace_id, context, and steps
        fleet_id: Fleet ID from JWT token
        
    Returns:
        Updated MCP envelope with step outputs
    """
    # Extract and validate query from context
    query = await validate_mcp_envelope(envelope)
    
    # Process each step that doesn't have output yet
    await process_pending_steps(envelope, query, fleet_id)
    
    return envelope

# Conditionally add MCP endpoint if enabled
if ENABLE_MCP:
    @app.post("/mcp")
    async def mcp_endpoint(
        envelope: MCPEnvelope,
        fleet_id: int = Depends(get_fleet_id)
    ):
        """
        Process a request through the Model Context Protocol.
        
        Args:
            envelope: MCP envelope with trace_id, context, and steps
            fleet_id: Fleet ID from JWT token
            
        Returns:
            Updated MCP envelope with step outputs
        """
        try:
            return await handle_mcp_request(envelope, fleet_id)
        except HTTPException:
            # Re-raise HTTP exceptions without modification
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
