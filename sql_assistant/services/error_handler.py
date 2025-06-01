"""
Error handling utilities for SQL Assistant.

This module provides functionality for:
1. Detecting and correcting common SQL errors
2. Tracking error patterns
3. Generating user-friendly error messages
"""
import re
import yaml
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from collections import defaultdict
import os

class ErrorHandler:
    def __init__(self):
        self.error_patterns = self._load_error_patterns()
        self.business_concepts = self._load_business_concepts()
        self.error_stats = defaultdict(int)
        self.recent_errors = []
    
    def _load_error_patterns(self) -> Dict[str, Any]:
        """Load error pattern configuration"""
        config_path = os.path.join(os.path.dirname(__file__), 'error_patterns.yaml')
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config.get('error_patterns', [])
    
    def _load_business_concepts(self) -> Dict[str, Any]:
        """Load business concept configuration"""
        config_path = os.path.join(os.path.dirname(__file__), 'error_patterns.yaml')
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        return config.get('business_concepts', {})
    
    def detect_error(self, sql: str, error_message: str) -> Tuple[str, Optional[str]]:
        """
        Detect SQL errors and attempt to correct them
        
        Returns:
            Tuple[str, Optional[str]]: (error type, corrected SQL)
        """
        # Check for missing column errors
        if "column" in error_message.lower() and "does not exist" in error_message.lower():
            column_match = re.search(r'column ([\w.]+) does not exist', error_message, re.IGNORECASE)
            if column_match:
                bad_column = column_match.group(1)
                return self._handle_missing_column(bad_column, sql)
        
        # Check for other common mistakes
        for pattern in self.error_patterns:
            for mistake in pattern['common_mistakes']:
                if mistake in sql:
                    return self._handle_common_mistake(pattern, sql)
        
        return "unknown_error", None
    
    def _handle_missing_column(self, bad_column: str, sql: str) -> Tuple[str, Optional[str]]:
        """Handle missing column error"""
        # Track the error
        self._track_error("missing_column", sql, bad_column)
        
        # Check if it matches a known error pattern
        for pattern in self.error_patterns:
            if bad_column in pattern['common_mistakes']:
                return self._handle_common_mistake(pattern, sql)
        
        return "missing_column", None
    
    def _handle_common_mistake(self, pattern: Dict[str, Any], sql: str) -> Tuple[str, Optional[str]]:
        """Handle common mistake pattern"""
        # Track the error
        self._track_error(pattern['name'], sql)
        
        # Try to use correction template
        if 'correction_template' in pattern:
            return pattern['name'], pattern['correction_template']
        
        return pattern['name'], None
    
    def _track_error(self, error_type: str, sql: str, details: str = ""):
        """Track error information"""
        error_info = {
            'error_type': error_type,
            'sql': sql,
            'details': details,
            'timestamp': datetime.now().isoformat()
        }
        self.error_stats[error_type] += 1
        self.recent_errors.append(error_info)
        # Only keep the latest 100 error records
        if len(self.recent_errors) > 100:
            self.recent_errors.pop(0)
    
    def get_error_stats(self) -> Dict[str, Any]:
        """Get error statistics"""
        return {
            'total_errors': sum(self.error_stats.values()),
            'error_types': dict(self.error_stats),
            'recent_errors': self.recent_errors[-10:] if self.recent_errors else []
        }
    
    def get_business_concept(self, concept_name: str) -> Optional[Dict[str, Any]]:
        """Get business concept definition"""
        return self.business_concepts.get(concept_name)
    
    def get_user_friendly_error(self, error_type: str, details: str = "") -> str:
        """Generate user-friendly error message"""
        if error_type == "missing_column":
            return f"I encountered an error with the column '{details}' which doesn't exist in our database. Please try rephrasing your question."
        
        for pattern in self.error_patterns:
            if pattern['name'] == error_type:
                return f"I encountered an error: {pattern['description']}. Please try rephrasing your question."
        
        return "I encountered an error while processing your request. Please try rephrasing your question."

# Global error handler instance
error_handler = ErrorHandler() 