"""
Unit tests for MCP schema.

Tests validation and serialization of MCP envelope and steps.
"""
import pytest
import uuid
from pydantic import ValidationError
from sql_assistant.schemas.mcp import MCPEnvelope, Step

def test_valid_step():
    """Test that valid Step objects can be created."""
    # Test with minimal fields
    step1 = Step(tool="nl_to_sql")
    assert step1.tool == "nl_to_sql"
    assert step1.input is None
    assert step1.output is None
    
    # Test with input
    step2 = Step(tool="nl_to_sql", input={"query": "test"})
    assert step2.tool == "nl_to_sql"
    assert step2.input == {"query": "test"}
    assert step2.output is None
    
    # Test with output
    step3 = Step(tool="sql_exec", output={"rows": []})
    assert step3.tool == "sql_exec"
    assert step3.input is None
    assert step3.output == {"rows": []}
    
    # Test with string output
    step4 = Step(tool="answer_format", output="This is an answer")
    assert step4.tool == "answer_format"
    assert step4.input is None
    assert step4.output == "This is an answer"

def test_invalid_step_tool():
    """Test that Step with invalid tool fails validation."""
    with pytest.raises(ValidationError):
        Step(tool="invalid_tool")

def test_valid_envelope():
    """Test that valid MCPEnvelope objects can be created."""
    # Test with minimal fields
    trace_id = uuid.uuid4()
    envelope1 = MCPEnvelope(trace_id=trace_id, steps=[])
    assert envelope1.trace_id == trace_id
    assert envelope1.context is None
    assert envelope1.steps == []
    
    # Test with context and steps
    envelope2 = MCPEnvelope(
        trace_id=trace_id,
        context={"query": "test"},
        steps=[Step(tool="nl_to_sql")]
    )
    assert envelope2.trace_id == trace_id
    assert envelope2.context == {"query": "test"}
    assert len(envelope2.steps) == 1
    assert envelope2.steps[0].tool == "nl_to_sql"

def test_envelope_serialization():
    """Test that MCPEnvelope can be serialized to and from JSON."""
    trace_id = uuid.uuid4()
    original = MCPEnvelope(
        trace_id=trace_id,
        context={"query": "test"},
        steps=[
            Step(tool="nl_to_sql", output={"sql": "SELECT * FROM test"}),
            Step(tool="sql_exec", output={"rows": [{"id": 1}]}),
            Step(tool="answer_format", output="Test result")
        ]
    )
    
    # Convert to JSON and back
    json_data = original.model_dump_json()
    deserialized = MCPEnvelope.model_validate_json(json_data)
    
    # Check that the objects are equivalent
    assert deserialized.trace_id == original.trace_id
    assert deserialized.context == original.context
    assert len(deserialized.steps) == len(original.steps)
    
    for i, step in enumerate(original.steps):
        assert deserialized.steps[i].tool == step.tool
        assert deserialized.steps[i].input == step.input
        assert deserialized.steps[i].output == step.output

def test_envelope_with_all_tools():
    """Test that MCPEnvelope can contain all supported tools."""
    envelope = MCPEnvelope(
        trace_id=uuid.uuid4(),
        context={"query": "test"},
        steps=[
            Step(tool="nl_to_sql"),
            Step(tool="sql_exec"),
            Step(tool="answer_format")
        ]
    )
    
    assert len(envelope.steps) == 3
    assert [step.tool for step in envelope.steps] == ["nl_to_sql", "sql_exec", "answer_format"]
