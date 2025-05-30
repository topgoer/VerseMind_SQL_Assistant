"""
Test configuration and fixtures for the VerseMind SQL Assistant.

This module provides common test fixtures and configuration for both unit and integration tests.
"""
import os
import pytest
import asyncio
import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Override database settings for tests
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", 
    os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/sql_assistant_test")
)

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def database_url():
    """Provide the test database URL."""
    return TEST_DATABASE_URL

@pytest.fixture(scope="session")
async def db_engine():
    """Create a database engine for testing."""
    engine = create_async_engine(TEST_DATABASE_URL)
    yield engine
    await engine.dispose()

@pytest.fixture(scope="session")
async def db_session_factory(db_engine):
    """Create a session factory for database operations."""
    async_session = sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    return async_session

@pytest.fixture
async def db_session(db_session_factory):
    """Create a database session for individual tests."""
    async with db_session_factory() as session:
        yield session

@pytest.fixture(scope="session") 
async def db_connection():
    """Create a raw database connection for testing."""
    # Extract connection parameters from DATABASE_URL
    import re
    url_pattern = r"postgresql\+?(?:asyncpg)?://(\w+):(\w+)@([^:]+):(\d+)/(\w+)"
    match = re.match(url_pattern, TEST_DATABASE_URL)
    
    if match:
        user, password, host, port, database = match.groups()
        conn = await asyncpg.connect(
            user=user,
            password=password,
            host=host,
            port=int(port),
            database=database
        )
        yield conn
        await conn.close()
    else:
        # Fallback to environment variables
        conn = await asyncpg.connect(
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "postgres"),
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            database=os.environ.get("DB_NAME", "sql_assistant_test")
        )
        yield conn
        await conn.close()

@pytest.fixture(autouse=True)
def setup_test_environment():
    """Set up test environment variables."""
    # Ensure we have required environment variables for tests
    if not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "dummy_key_for_tests"
    
    if not os.environ.get("JWT_PUBLIC_KEY"):
        os.environ["JWT_PUBLIC_KEY"] = "dummy_jwt_public_key_for_tests"
        
    # Set test database URL
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
