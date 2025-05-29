# Environment Variables Setup Guide

This document provides instructions on how to properly set up environment variables for the VerseMind SQL Assistant project.

## Required Environment Variables

The following environment variables must be set in your development environment or in a `.env` file:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DB_USER` | Database username | No | `postgres` |
| `DB_PASSWORD` | Database password | **Yes** | (none) |
| `OPENAI_API_KEY` | OpenAI API key | Yes | (none) |
| `ANTHROPIC_API_KEY` | Anthropic API key | No | (none) |
| `MISTRAL_API_KEY` | Mistral API key | No | (none) |
| `JWT_PUBLIC_KEY` | JWT public key for auth | Yes | (none) |
| `ENABLE_MCP` | Enable Model Context Protocol | No | `0` |

## Setting Up Your Environment

### Development Environment

1. Create a `.env` file at the root of the project directory
2. Add your required environment variables:

```
DB_USER=postgres
DB_PASSWORD=your_secure_password
OPENAI_API_KEY=your_openai_key
JWT_PUBLIC_KEY=your_jwt_public_key
ENABLE_MCP=1
```

### Production Environment

For production deployments, set environment variables securely through your hosting platform's environment configuration:

- Docker: Use environment variables or Docker secrets
- Cloud platforms: Use the platform's environment variable or secrets management system

## Security Best Practices

1. **Never commit passwords or API keys** to version control
2. Use different passwords for development and production environments
3. Regularly rotate your database passwords and API keys
4. Use environment-specific `.env` files (e.g., `.env.development`, `.env.production`)

## Testing Your Setup

To verify your environment variables are properly set:

```bash
# Windows (PowerShell)
Get-ChildItem Env: | Where-Object { $_.Name -eq "DB_PASSWORD" }

# Linux/macOS
echo $DB_PASSWORD
```

## Docker Compose Usage

When using Docker Compose, ensure your environment variables are set before running:

```bash
docker-compose up
```

If you're using a specific profile, such as the seed profile:

```bash
docker-compose --profile seed up
```

## Docker Security Notes

- The application uses a multi-stage Docker build with `python:3.12-slim` for improved security
- Security features implemented:
  - Python 3.12 (latest stable version with security improvements)
  - Multi-stage build (separates build dependencies from runtime)
  - Non-root user execution (runs as `appuser` not root)
  - Minimal runtime dependencies with only required packages
  - No build tools in final image
  - Dependencies installed from pre-built wheels
  - Proper file permissions applied

This approach balances security with simplicity, focusing on the most important security practices without overcomplicating the Docker setup.
- Regular rebuilds of the Docker image are recommended to incorporate security patches

## Docker Image Security Scanning

Docker vulnerability scanners may report vulnerabilities in the base Python images. Here's how to handle these warnings:

1. **Understand the context**: Many reported vulnerabilities may not impact your application directly.

2. **Regular updates**: Rebuild the Docker image regularly to incorporate security patches.

3. **Risk assessment**: For vulnerabilities in the base image, evaluate if they affect components actually used by your application.

Our Docker setup implements best practices for basic container security:
- Non-root user execution
- Multi-stage builds to minimize attack surface
- Minimal runtime dependencies
- Clean removal of build artifacts

## Production Security Considerations

For production deployments, consider these additional security measures:

1. **Keep Images Updated**: Regularly rebuild Docker images with the latest base images and dependencies
2. **Network Security**: Properly configure firewalls and network policies
3. **Monitoring**: Implement runtime monitoring for container behavior
4. **Updates**: Have a process for applying security patches quickly

Remember that container security is just one aspect of a complete security strategy that should also include network security, access controls, and application-level security measures.
