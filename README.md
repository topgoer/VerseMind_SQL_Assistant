# VerseMind SQL Assistant

[![CI](https://github.com/topgoer/versemind-sql-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/topgoer/versemind-sql-assistant/actions/workflows/ci.yml)

A natural language analytics layer for fleet operators with dual interface support for standard chat and Model Control Protocol (MCP).

![SQL Assistant Screenshot](./frontend/public/screenshot.png)

## Features

- **Natural Language to SQL**: Convert plain English questions to SQL queries
- **Dual Interface**: Standard chat endpoint and MCP (Model Control Protocol) support
- **Security**: Row-Level Security (RLS) for multi-tenant data isolation
- **Frontend**: React SPA with adjustable panels for chat and MCP interaction
- **Deployment**: Docker setup for one-command startup

## Quick Start

### Prerequisites

- Docker and Docker Compose v2+ (the project uses modern Compose features)
- OpenAI API key (or Anthropic/Mistral as fallbacks)

### Installation

1. Clone the repository:

```bash
git clone https://github.com/topgoer/sql-assistant.git
cd sql-assistant
```

2. Create a `.env` file from the example:

```bash
cp .env.example .env
```

3. Edit the `.env` file to add your database connection and at least one LLM API key:

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/sql_assistant
OPENAI_API_KEY=your_openai_api_key
# Optional fallbacks
# ANTHROPIC_API_KEY=your_anthropic_api_key
# MISTRAL_API_KEY=your_mistral_api_key
ENABLE_MCP=1  # Set to 1 to enable Model Control Protocol support
```

   Note: The JWT_PUBLIC_KEY environment variable is not needed as the public.pem file is directly mounted in the container.

4. Start the application:

```bash
docker compose up -d
```

5. Generate authentication keys and JWT token:

```bash
# Generate public.pem, private.pem and a JWT token for fleet_id=1
python scripts/gen_keys_and_jwt.py 

# You can specify a different fleet_id
# python scripts/gen_keys_and_jwt.py 2
```

   This script creates public.pem and private.pem files in the project root, which are used for JWT authentication. 
   The public.pem file is automatically mounted into the Docker container - no need to set JWT_PUBLIC_KEY environment variable.

6. Import sample data (one-time setup):

```bash
docker compose --profile seed up

# This command imports all CSV files from the 'upload' directory into the database,
# creates necessary tables, and sets up Row-Level Security (RLS) policies
```

   Note: The seed service uses the same environment variables from your `.env` file.

7. Access the application:
   - Frontend: http://localhost:3000
   - API: http://localhost:8000

### Verifying Data Import

To check if the data import was successful:

```bash
# Check import logs
docker compose logs seed
```

You should see messages like "Imported X rows into [table_name]" for each CSV file and "Database setup completed successfully!" at the end.

**Troubleshooting Import Issues**:
- Ensure all required CSV files are in the `upload` directory
- If Docker has connection issues, try `docker compose down` first, then restart
- Wait for the database service to be fully initialized before running the seed command
- The seed service automatically truncates tables before importing, so it's safe to run multiple times

**Updating API Keys**:
If you need to update your API key or other environment variables:
1. Edit the `.env` file with your new values
2. Run the included script to recreate containers with fresh environment variables:
```bash
./restart_docker_with_env.ps1  # On Windows
# or
bash restart_docker_with_env.sh  # On Linux/Mac (if available)
```
This script completely recreates containers to ensure they use the latest environment variables.

## API Endpoints

### Chat Endpoint

```
POST /chat
```

Request body:
```json
{
  "query": "How many vehicles are in the fleet?",
  "fleet_id": 1
}
```

Response:
```json
{
  "answer": "There are 42 vehicles in fleet 1.",
  "sql": "SELECT COUNT(*) FROM vehicles WHERE fleet_id = :fleet_id LIMIT 5000",
  "rows": [{"count": 42}],
  "download_url": null
}
```

### MCP Endpoint

```
POST /mcp
```

Request body:
```json
{
  "query": "How many vehicles are in the fleet?",
  "fleet_id": 1,
  "tools": ["nl_to_sql", "sql_exec", "answer_format"]
}
```

Response:
```json
{
  "trace": [
    {
      "tool": "nl_to_sql",
      "input": {"query": "How many vehicles are in the fleet?", "fleet_id": 1},
      "output": {"sql": "SELECT COUNT(*) FROM vehicles WHERE fleet_id = :fleet_id LIMIT 5000"}
    },
    {
      "tool": "sql_exec",
      "input": {"sql": "SELECT COUNT(*) FROM vehicles WHERE fleet_id = :fleet_id LIMIT 5000", "fleet_id": 1},
      "output": {"rows": [{"count": 42}]}
    },
    {
      "tool": "answer_format",
      "input": {
        "query": "How many vehicles are in the fleet?",
        "sql_result": {"rows": [{"count": 42}]},
        "sql": "SELECT COUNT(*) FROM vehicles WHERE fleet_id = :fleet_id LIMIT 5000"
      },
      "output": "There are 42 vehicles in fleet 1."
    }
  ],
  "answer": "There are 42 vehicles in fleet 1.",
  "sql": "SELECT COUNT(*) FROM vehicles WHERE fleet_id = :fleet_id LIMIT 5000",
  "rows": [{"count": 42}],
  "download_url": null
}
```

## Development

### Backend Setup

1. Create a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the development server:

```bash
uvicorn sql_assistant.main:app --reload
```

### Frontend Setup (React + TypeScript)

The frontend is a modern React Single Page Application (SPA) built with TypeScript, Vite, and Tailwind CSS.

1. Navigate to the frontend directory:

```bash
cd frontend
```

2. Install dependencies:

```bash
npm install
```

3. Start the development server:

```bash
npm run dev
```

- The app will be available at http://localhost:5173/
- The frontend will automatically proxy API requests to the backend (see `vite.config.ts` for proxy settings).

#### Troubleshooting
- If you see styling issues, ensure you are using Tailwind CSS v3 (see `package.json`).
- If you get 404 errors for API calls, make sure your backend is running and the proxy is configured in `vite.config.ts`.
- If you see dependency errors during `npm install`, use `npm install --legacy-peer-deps` or update your Node/npm version.
- For TypeScript or module errors in your editor, ensure you have run `npm install` and restart your editor.

#### Building for Production

To build the frontend for production:

```bash
npm run build
```

The output will be in the `dist/` directory.

## Testing

### Running Tests

```bash
# Run unit tests
pytest tests/unit/

# Run integration tests
pytest tests/integration/

# Run with coverage
pytest --cov=sql_assistant tests/
```

### Test Requirements

- Unit tests require at least one LLM API key set in the environment
- Integration tests require a running PostgreSQL database

## Project Structure

```
sql_assistant/
├── .github/                    # GitHub configuration files
│   └── workflows/             # CI/CD workflows
├── db/                        # Database related files
├── examples/                  # Example code and usage
│   └── call_mcp.py           # MCP client example
├── scripts/                   # Utility scripts
├── static/                    # Static assets
│   ├── chat.html             # Web-based chat interface
│   └── screenshot.png        # Project screenshot
├── temp/                      # Temporary files
├── tests/                     # Test suite
│   ├── integration/          # Integration tests
│   └── unit/                 # Unit tests
├── sql_assistant/            # Main application code
│   ├── services/             # Business logic services
│   ├── schemas/              # Data models and schemas
│   ├── main.py              # FastAPI application entry point
│   ├── guardrails.py        # Query validation and safety checks
│   ├── auth.py              # Authentication and authorization
│   └── __init__.py          # Package initialization
├── frontend/                 # React SPA frontend
│   ├── public/               # Static assets
│   ├── src/                  # Source code
│   │   ├── components/       # React components
│   │   ├── services/         # API services
│   │   └── styles/           # CSS styles
│   ├── package.json         # NPM dependencies
│   └── vite.config.ts       # Vite configuration
├── .env.example              # Example environment variables
├── docker-compose.yml        # Docker Compose configuration
├── Dockerfile               # Docker build instructions
├── README.md                # Project documentation
└── requirements.txt         # Python dependencies
```

## Security

- All SQL queries are validated to ensure they:
  - Include a fleet_id filter for tenant isolation
  - Have a LIMIT clause (max 5000 rows)
  - Contain no SQL comments
  - Use only SELECT statements (no modifications)
- JWT authentication ensures users can only access their own fleet data
- Row-Level Security (RLS) enforces data isolation at the database level

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## JWT Token Generation for Testing

To test authenticated endpoints, you need a valid JWT token and a matching public key file.

### Generate Keys and Token in One Step

Use the provided script to generate a key pair and JWT token in one step:

```bash
# Generate for fleet_id=1 (default)
python scripts/gen_keys_and_jwt.py

# Or specify a different fleet_id
python scripts/gen_keys_and_jwt.py 2
```

This script:
- Creates `private.pem` and `public.pem` in the project root
- Automatically generates a JWT token for the specified fleet ID
- Prints the token for immediate use with API requests

### Alternative: Manual Generation

If you prefer, you can still generate keys and tokens separately:

1. Generate a key pair with OpenSSL:
```bash
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem
```

2. Use the make_dummy_jwt.py script:
```bash
python scripts/make_dummy_jwt.py --fleet 1 --private-key private.pem
```

- Replace `1` with your desired fleet ID
- Replace `private.pem` with your private key path if different

The script will output a JWT token you can use for API requests (e.g., as an Authorization header).

## Domain Glossary Knowledge Base

A domain-specific glossary is provided to help the LLM understand key terms and context in the EV/fleet management domain. This glossary is located at:

- `sql_assistant/services/domain_glossary.py`

It contains definitions and explanations for terms such as SOH (State of Health), SOC (State of Charge), SRM T3, VIN, Trip, Charging session, and more. The glossary is automatically injected into LLM prompts when generating human-readable answers, improving the accuracy and relevance of responses.

**How it works:**
- The glossary is formatted and prepended to the LLM context in the answer formatting pipeline.
- This ensures that the LLM always has access to domain definitions and relationships when answering user queries.

Feel free to update or expand the glossary as your data or use cases evolve.
