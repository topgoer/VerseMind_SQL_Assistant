#!/bin/bash

# Stop and remove existing containers
docker compose down

# Rebuild and start containers
docker compose up -d --build

# Wait for services to be ready
echo "Waiting for services to be ready..."
sleep 10

# Run tests
PYTHONPATH=. pytest --cov=sql_assistant --cov-report=xml

# Show container logs
docker compose logs 