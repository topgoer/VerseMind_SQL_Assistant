"""
Authentication module for VerseMind SQL Assistant.

Handles JWT validation and fleet_id extraction.
"""
import os
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

def get_jwt_public_key():
    with open("/app/public.pem", "r") as f:
        return f.read().replace('\r\n', '\n').replace('\r', '\n')

security = HTTPBearer()

class AuthError(Exception):
    """Custom exception for authentication errors."""
    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

async def get_fleet_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> int:
    """
    Extract fleet_id from JWT token and set it in the app state.
    
    Args:
        request: FastAPI request object
        credentials: JWT credentials from Authorization header
        
    Returns:
        fleet_id: The fleet ID extracted from the JWT token
        
    Raises:
        HTTPException: If token is invalid or missing fleet_id claim
    """
    try:
        token = credentials.credentials
        
        # Decode JWT token using RS256 algorithm
        payload = jwt.decode(
            token,
            get_jwt_public_key(),
            algorithms=["RS256"],
            options={"verify_aud": False}
        )
        
        # Extract fleet_id from token
        fleet_id = payload.get("fleet_id")
        if not fleet_id:
            raise AuthError("Token missing fleet_id claim")
        
        # Set fleet_id in request state for middleware
        request.state.fleet_id = fleet_id
        
        return fleet_id
    
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except AuthError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail=e.message,
            headers={"WWW-Authenticate": "Bearer"},
        )

class FleetMiddleware:
    """Middleware to set fleet_id in PostgreSQL session."""
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        """
        ASGI middleware that sets app.fleet_id in PostgreSQL session.
        
        This enables Row-Level Security policies to filter data by fleet_id.
        """
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        
        # Create a request object to access state
        request = Request(scope, receive=receive, send=send)
        
        # Check if fleet_id is set in request state (by auth dependency)
        fleet_id = getattr(request.state, "fleet_id", None)
        
        # If fleet_id is set, ensure it's applied to database session
        if fleet_id is not None:
            # This will be handled by the database connection middleware
            # which will execute SET app.fleet_id = :fleet_id
            scope["fleet_id"] = fleet_id
        
        return await self.app(scope, receive, send)
