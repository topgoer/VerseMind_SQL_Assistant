import os
import sys
import argparse
import subprocess
from jose import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
import datetime

# Define constants for file paths
PRIVATE_KEY_FILE = "private.pem"
PUBLIC_KEY_FILE = "public.pem"
ENV_FILE = ".env"

def parse_args():
    parser = argparse.ArgumentParser(description="Generate RSA key pair and JWT token for a specific fleet_id")
    parser.add_argument("fleet_id", nargs="?", type=int, default=1, help="Fleet ID to include in the JWT token (default: 1)")
    parser.add_argument("--force", "-f", action="store_true", help="Force regeneration of keys even if they already exist")
    parser.add_argument("--update-docker", "-d", action="store_true", help="Update Docker environment and restart container after key generation")
    return parser.parse_args()

def generate_keys(force=False):
    """Generate RSA keys if they don't exist or if forced to regenerate"""
    if not force and os.path.exists(PUBLIC_KEY_FILE) and os.path.exists(PRIVATE_KEY_FILE):
        print("Keys already exist. Using existing keys.")
        return False
    
    print("Generating new RSA key pair...")
    # Generate RSA key pair
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # Write private key to private.pem
    with open(PRIVATE_KEY_FILE, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    # Write public key to public.pem
    public_key = private_key.public_key()
    with open(PUBLIC_KEY_FILE, "wb") as f:
        f.write(public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))
    
    return True

def update_env_file():
    """Update .env file with JWT_PUBLIC_KEY"""
    # Read public key
    with open(PUBLIC_KEY_FILE, "r") as f:
        public_key = f.read()
    
    # Format the key for .env file
    # Replace newlines with literal '\n' for .env file format
    env_key = public_key.replace("\n", "\\n")
    
    # Check if .env exists and if it already has JWT_PUBLIC_KEY
    env_content = ""
    key_exists = False
    
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            env_content = f.read()
        
        # Check if JWT_PUBLIC_KEY is already in the file
        if "JWT_PUBLIC_KEY=" in env_content:
            # Replace the existing key
            lines = env_content.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("JWT_PUBLIC_KEY="):
                    lines[i] = f'JWT_PUBLIC_KEY="{env_key}"'
                    key_exists = True
                    break
            env_content = "\n".join(lines)
        
    # If key doesn't exist, append it
    if not key_exists:
        if env_content and not env_content.endswith("\n"):
            env_content += "\n"
        env_content += f'JWT_PUBLIC_KEY="{env_key}"\n'
      # Write back to .env file
    with open(ENV_FILE, "w") as f:
        f.write(env_content)
    
    print("Updated .env file with JWT_PUBLIC_KEY")

def restart_docker_container():
    """Restart the web container to apply new key"""
    try:
        print("Restarting Docker web container...")
        # Check if Docker is running first
        check_result = subprocess.run(
            ["docker", "ps"], 
            capture_output=True, 
            text=True,
            timeout=5
        )
        
        if check_result.returncode != 0:
            print(f"Docker doesn't seem to be running: {check_result.stderr}")
            print("Please start Docker and then manually restart the container with:")
            print("docker compose restart web")
            return
            
        # Restart with timeout to avoid hanging
        result = subprocess.run(
            ["docker", "compose", "restart", "web"], 
            capture_output=True, 
            text=True,
            timeout=30  # Add 30-second timeout
        )
        
        if result.returncode == 0:
            print("Docker container restarted successfully.")
        else:
            print(f"Error restarting Docker container: {result.stderr}")
    except subprocess.TimeoutExpired:
        print("Docker restart command timed out after 30 seconds.")
        print("This might mean Docker is busy or the container is having issues.")
        print("Try manually running: docker compose restart web")
    except Exception as e:
        print(f"Failed to restart Docker container: {e}")
        print("Please try manually restarting with: docker compose restart web")

def keys_match(public_key_path="public.pem", private_key_path="private.pem"):
    # Load public key
    with open(public_key_path, "rb") as f:
        public_pem = f.read()
    public_key = serialization.load_pem_public_key(public_pem, backend=default_backend())

    # Load private key
    with open(private_key_path, "rb") as f:
        private_pem = f.read()
    private_key = serialization.load_pem_private_key(private_pem, password=None, backend=default_backend())

    # Compare public numbers
    return public_key.public_numbers() == private_key.public_key().public_numbers()

# Main execution
args = parse_args()
fleet_id = args.fleet_id
keys_generated = generate_keys(args.force)

# Always update .env file to ensure JWT_PUBLIC_KEY is set
update_env_file()

# Restart Docker container if requested or if new keys were generated
if args.update_docker or keys_generated:
    print("Checking Docker container status...")
    try:
        # Check if the web container is running
        container_check = subprocess.run(
            ["docker", "compose", "ps", "web", "--format", "json"], 
            capture_output=True, 
            text=True,
            timeout=5
        )
        
        if "running" not in container_check.stdout.lower():
            print("Docker web container doesn't seem to be running.")
            print("Start the container first with: docker compose up -d web")
            print("Then you can restart it with: docker compose restart web")
        else:
            restart_docker_container()
    except Exception as e:
        print(f"Couldn't check container status: {e}")
        restart_docker_container()  # Try anyway

# Check key pair before generating JWT
if not keys_match():
    print("ERROR: public.pem and private.pem DO NOT match! JWT will not be valid.")
    exit(1)
else:
    print("public.pem and private.pem match. Proceeding to generate JWT.")

# Read private key for JWT
with open(PRIVATE_KEY_FILE, "r") as f:
    privkey = f.read()

# Generate JWT
payload = {
    "sub": "tester",
    "fleet_id": fleet_id,
    "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
}
token = jwt.encode(payload, privkey, algorithm="RS256")

print(f"Generated JWT for fleet_id={fleet_id}:")
print(token)
print(f"\n{PUBLIC_KEY_FILE} and {PRIVATE_KEY_FILE} have been created at:")
print(os.path.abspath(PUBLIC_KEY_FILE))
print(os.path.abspath(PRIVATE_KEY_FILE))
print("\nTo use this token with Docker:")
print("1. The .env file has been updated with the JWT_PUBLIC_KEY")
if args.update_docker or keys_generated:
    print("2. The Docker web container has been restarted")
else:
    print("2. Use --update-docker flag to restart the Docker container")
print("3. Access the chat interface at http://localhost:8001/chat.html")