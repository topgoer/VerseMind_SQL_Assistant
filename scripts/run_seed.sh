#!/bin/bash
# Seed script for importing data into the database

# Install required dependency first
echo "Installing required dependencies..."
# Use --no-warn-script-location and other flags to suppress all pip warnings
pip install python-dotenv --quiet --no-warn-script-location --disable-pip-version-check 2>/dev/null

# Wait for database to be ready
echo "Waiting for database to be ready..."
sleep 5

# Run import script
echo "Importing data..."
python -m db.import_data

echo "Seed completed!"
