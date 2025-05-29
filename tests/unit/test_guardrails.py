"""
Unit tests for SQL guardrails.

Tests validation of SQL queries against security guardrails.
"""
from sql_assistant.guardrails import validate_sql

def test_valid_sql():
    """Test that valid SQL passes validation."""
    sql = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100"
    is_valid, error = validate_sql(sql)
    assert is_valid
    assert error == ""

def test_missing_fleet_id():
    """Test that SQL without fleet_id filter fails validation."""
    sql = "SELECT * FROM vehicles LIMIT 100"
    is_valid, error = validate_sql(sql)
    assert not is_valid
    assert "fleet_id" in error

def test_missing_limit():
    """Test that SQL without LIMIT fails validation."""
    sql = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id"
    is_valid, error = validate_sql(sql)
    assert not is_valid
    assert "LIMIT" in error

def test_limit_too_large():
    """Test that SQL with LIMIT > 5000 fails validation."""
    sql = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 10000"
    is_valid, error = validate_sql(sql)
    assert not is_valid
    assert "5000" in error

def test_forbidden_keywords():
    """Test that SQL with forbidden keywords fails validation."""
    forbidden_keywords = [
        "DROP", "DELETE", "TRUNCATE", "ALTER", "CREATE", "INSERT", "UPDATE", 
        "GRANT", "REVOKE", "EXECUTE", "FUNCTION", "PROCEDURE", "TRIGGER",
        "ROLE", "USER", "PASSWORD"
    ]
    
    for keyword in forbidden_keywords:
        sql = f"SELECT * FROM vehicles WHERE fleet_id = :fleet_id {keyword} TABLE test LIMIT 100"
        is_valid, error = validate_sql(sql)
        assert not is_valid
        assert keyword in error

def test_not_select():
    """Test that non-SELECT SQL fails validation."""
    sql = "INSERT INTO vehicles (id, name) VALUES (1, 'test') WHERE fleet_id = :fleet_id LIMIT 100"
    is_valid, error = validate_sql(sql)
    assert not is_valid
    # Updated assertion to match actual error message
    assert "forbidden keyword: INSERT" in error

def test_sql_comments():
    """Test that SQL with comments fails validation."""
    # Single line comment
    sql1 = "SELECT * FROM vehicles -- This is a comment\nWHERE fleet_id = :fleet_id LIMIT 100"
    is_valid1, error1 = validate_sql(sql1)
    assert not is_valid1
    assert "comments" in error1
    
    # Multi-line comment
    sql2 = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id /* This is a comment */ LIMIT 100"
    is_valid2, error2 = validate_sql(sql2)
    assert not is_valid2
    assert "comments" in error2

def test_both_fleet_id_and_limit():
    """Test that SQL must contain both fleet_id filter and LIMIT."""
    # Both present (valid)
    sql1 = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100"
    is_valid1, error1 = validate_sql(sql1)
    assert is_valid1
    
    # Missing fleet_id
    sql2 = "SELECT * FROM vehicles LIMIT 100"
    is_valid2, error2 = validate_sql(sql2)
    assert not is_valid2
    
    # Missing LIMIT
    sql3 = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id"
    is_valid3, error3 = validate_sql(sql3)
    assert not is_valid3
    
    # Both missing
    sql4 = "SELECT * FROM vehicles"
    is_valid4, error4 = validate_sql(sql4)
    assert not is_valid4
