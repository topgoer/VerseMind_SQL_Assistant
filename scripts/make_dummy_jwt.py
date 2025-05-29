#!/usr/bin/env python3
import argparse
import datetime
import jwt
import pathlib
import sys

def generate_token(fleet_id: int, private_key_path: str) -> str:
    """Generate a JWT token for testing."""
    try:
        private_key = pathlib.Path(private_key_path).read_text()
    except FileNotFoundError:
        print(f"Error: Private key file not found at {private_key_path}")
        sys.exit(1)

    payload = {
        "sub": "tester",
        "fleet_id": fleet_id,
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    }

    try:
        token = jwt.encode(payload, private_key, algorithm="RS256")
        return token
    except Exception as e:
        print(f"Error generating token: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Generate a JWT token for testing")
    parser.add_argument("--fleet", type=int, required=True, help="Fleet ID to include in token")
    parser.add_argument("--private-key", type=str, required=True, help="Path to private key file")
    args = parser.parse_args()

    token = generate_token(args.fleet, args.private_key)
    print(token)

if __name__ == "__main__":
    main() 