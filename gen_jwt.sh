#!/bin/bash

# Shell script to generate JWT tokens for VerseMind SQL Assistant
# Usage: ./gen_jwt.sh [fleet_id]
# Example: ./gen_jwt.sh 3

# Default fleet_id to 1 if not provided
FLEET_ID=${1:-1}

echo "Generating JWT token for fleet_id=$FLEET_ID..."
echo ""

# Run the gen_keys_and_jwt.py script to generate the token
python scripts/gen_keys_and_jwt.py $FLEET_ID

echo ""
echo "To use this token:"
echo "1. Copy the JWT token shown above (valid for 1 hour)"
echo "2. Enter it in the authentication field at http://localhost:8001/chat.html"
echo ""
echo "Note: The Docker container uses the public.pem file directly mounted at /app/public.pem"
echo "You don't need to update the .env file with the JWT_PUBLIC_KEY." 