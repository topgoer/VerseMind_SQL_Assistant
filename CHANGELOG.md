# Changelog

## [1.0.1] - 2025-05-30

### Added
- Added `semantic_mapping.yaml` file for table-column mappings
- Added PyYAML dependency to requirements.txt

### Changed
- Updated `nl_to_sql` function to accept mappings as a parameter instead of using hardcoded mappings
- Updated function calls in main.py to pass semantic mappings to `nl_to_sql`
- Updated unit and integration tests to accommodate the new parameter
- Fixed authentication in integration tests

### Fixed
- Fixed SonarLint error (python:S930) related to missing arguments in function calls
- Improved test coverage for SQL semantic mappings
