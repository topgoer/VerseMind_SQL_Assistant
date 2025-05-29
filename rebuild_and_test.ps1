# Rebuild and test the SQL Assistant Docker containers
# This script:
# 1. Stops all running containers
# 2. Rebuilds the containers from scratch
# 3. Starts the containers 
# 4. Tests the API

# Stop all running containers
Write-Host "Stopping running containers..." -ForegroundColor Cyan
docker compose down

# Remove old images
Write-Host "Removing old images..." -ForegroundColor Cyan
docker image rm -f versemind_sql_assistant-web:latest

# Rebuild the image
Write-Host "Rebuilding Docker images from scratch..." -ForegroundColor Cyan
docker compose build --no-cache

# Start the containers
Write-Host "Starting containers..." -ForegroundColor Cyan
docker compose up -d

# Wait for the containers to start
Write-Host "Waiting for containers to start up (10 seconds)..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Show the logs
Write-Host "Container logs:" -ForegroundColor Cyan
docker compose logs

# Check if the API is up
Write-Host "Testing API endpoint..." -ForegroundColor Cyan
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8001/ping" -Method GET
    Write-Host "API is up and running! Response: $($response | ConvertTo-Json)" -ForegroundColor Green
} catch {
    Write-Host "Error: Failed to connect to API: $_" -ForegroundColor Red
}

Write-Host "Done!" -ForegroundColor Green
Write-Host "You can now test the application by opening http://localhost:8001/chat.html in your browser." -ForegroundColor Yellow
Write-Host "To view logs in real-time, use: docker compose logs -f" -ForegroundColor Yellow
