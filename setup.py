from setuptools import setup, find_packages

setup(
    name="sql_assistant",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "asyncpg",
        "python-jose[cryptography]",
        "passlib[bcrypt]",
        "python-multipart",
        "httpx",
        "openai",
        "anthropic",
        "mistralai",
        "pyyaml"
    ],
) 