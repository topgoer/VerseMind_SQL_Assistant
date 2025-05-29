@echo off
REM Simple batch file to generate JWT tokens for VerseMind SQL Assistant
REM Usage: gen_jwt.bat [fleet_id]
REM Example: gen_jwt.bat 3

setlocal

REM Get fleet ID from command line or default to 1
set FLEET_ID=1
if not "%~1"=="" set FLEET_ID=%~1

echo Generating JWT token for fleet_id=%FLEET_ID%...
echo.

REM Run the gen_keys_and_jwt.py script to generate the token
python scripts\gen_keys_and_jwt.py %FLEET_ID%

REM Extract just the token from the output (future enhancement)

echo.
echo To use this token:
echo 1. Copy the JWT token shown above (valid for 1 hour)
echo 2. Enter it in the authentication field at http://localhost:8001/chat.html
echo.
echo Note: The Docker container uses the public.pem file directly mounted at /app/public.pem
echo You don't need to update the .env file with the JWT_PUBLIC_KEY.

REM Keep the window open if double-clicked
if "%~1"=="" pause

endlocal
