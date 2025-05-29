"""
SQL Guardrails tests.

This module tests the validation functionality in guardrails.py.
"""
import sys
import unittest
from pathlib import Path

# Add the parent directory to the module search path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sql_assistant.guardrails import validate_sql, validate_sql_with_extraction, extract_sql_query


class TestSQLGuardrails(unittest.TestCase):
    """Tests for SQL guardrails."""

    def test_validate_sql_basic(self):
        """Test basic SQL validation."""
        valid_sql = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100"
        is_valid, message = validate_sql(valid_sql)
        self.assertTrue(is_valid, f"SQL should be valid, got: {message}")

    def test_must_start_with_select(self):
        """Test that SQL must start with SELECT."""
        invalid_sql = "DESCRIBE vehicles WHERE fleet_id = :fleet_id LIMIT 100"
        is_valid, message = validate_sql(invalid_sql)
        self.assertFalse(is_valid)
        self.assertEqual(message, "SQL must start with SELECT")

    def test_fleet_id_filter(self):
        """Test that SQL must contain fleet_id filter."""
        invalid_sql = "SELECT * FROM vehicles LIMIT 100"
        is_valid, message = validate_sql(invalid_sql)
        self.assertFalse(is_valid)
        self.assertEqual(message, "SQL must contain WHERE clause with fleet_id = :fleet_id")

    def test_limit_required(self):
        """Test that SQL must contain a LIMIT clause."""
        invalid_sql = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id"
        is_valid, message = validate_sql(invalid_sql)
        self.assertFalse(is_valid)
        self.assertEqual(message, "SQL must contain LIMIT clause")

    def test_limit_value(self):
        """Test that LIMIT value must be <= 5000."""
        invalid_sql = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 10000"
        is_valid, message = validate_sql(invalid_sql)
        self.assertFalse(is_valid)
        self.assertEqual(message, "LIMIT must be <= 5000, got 10000")

    def test_forbidden_keywords(self):
        """Test that SQL must not contain forbidden keywords."""
        invalid_sql = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id AND DELETE = 0 LIMIT 100"
        is_valid, message = validate_sql(invalid_sql)
        self.assertFalse(is_valid)
        self.assertEqual(message, "SQL contains forbidden keyword: DELETE")

    def test_no_comments(self):
        """Test that SQL must not contain comments."""
        invalid_sql = "SELECT * FROM vehicles -- Get all vehicles\nWHERE fleet_id = :fleet_id LIMIT 100"
        is_valid, message = validate_sql(invalid_sql)
        self.assertFalse(is_valid)
        self.assertEqual(message, "SQL contains comments, which are not allowed")

    def test_extract_sql_query(self):
        """Test extraction of SQL query from text."""
        # Text with SQL query
        text_with_sql = "Here is the SQL query:\nSELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100"
        extracted = extract_sql_query(text_with_sql)
        self.assertEqual(extracted, "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100")

        # Just SQL
        just_sql = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100"
        extracted = extract_sql_query(just_sql)
        self.assertEqual(extracted, just_sql)

        # SQL with semicolon
        sql_with_semi = "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100;"
        extracted = extract_sql_query(sql_with_semi)
        self.assertEqual(extracted, sql_with_semi)

    def test_validate_sql_with_extraction(self):
        """Test validation with extraction."""
        # Valid SQL with explanatory text
        text_with_valid_sql = "Here's a query to get vehicle data:\nSELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100"
        is_valid, message, extracted = validate_sql_with_extraction(text_with_valid_sql)
        self.assertTrue(is_valid, f"Extracted SQL should be valid, got: {message}")
        self.assertEqual(extracted, "SELECT * FROM vehicles WHERE fleet_id = :fleet_id LIMIT 100")

        # Invalid SQL with explanatory text
        text_with_invalid_sql = "Here's a query, but it's missing the fleet_id filter:\nSELECT * FROM vehicles LIMIT 100"
        is_valid, message, extracted = validate_sql_with_extraction(text_with_invalid_sql)
        self.assertFalse(is_valid)
        self.assertEqual(message, "SQL must contain WHERE clause with fleet_id = :fleet_id")
        self.assertEqual(extracted, "SELECT * FROM vehicles LIMIT 100")


if __name__ == "__main__":
    unittest.main()
