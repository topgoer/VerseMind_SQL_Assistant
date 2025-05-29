# PowerShell script to generate JWT tokens for VerseMind SQL Assistant
# Usage: .\gen_jwt.ps1 [fleet_id]
# Example: .\gen_jwt.ps1 3

param(
    [Parameter(Position=0)]
    [int]$FleetId = 1
)

Write-Host "Generating JWT token for fleet_id=$FleetId..."
Write-Host ""

# Run the gen_keys_and_jwt.py script to generate the token
python scripts\gen_keys_and_jwt.py $FleetId

Write-Host ""
Write-Host "To use this token:"
Write-Host "1. Copy the JWT token shown above (valid for 1 hour)"
Write-Host "2. Enter it in the authentication field at http://localhost:8001/chat.html"
Write-Host ""
Write-Host "Note: The Docker container uses the public.pem file directly mounted at /app/public.pem"
Write-Host "You don't need to update the .env file with the JWT_PUBLIC_KEY."

# If the script was run directly from Explorer (no arguments were passed)
if ($MyInvocation.Line -eq $MyInvocation.MyCommand.Path) {
    Write-Host ""
    Write-Host "Press any key to continue..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
