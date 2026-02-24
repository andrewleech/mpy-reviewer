---
timestamp: 2026-02-23T00:00:00Z
research_topic: "MCP streamable-http transport authentication headers support"
---

# MCP Streamable-HTTP Authentication: Summary

## Executive Summary

**YES** - Both the MCP client (Claude Code) and server implementations (FastMCP) support custom headers for authentication with streamable-http transport.

## 1. Claude Code MCP Client Config

### Headers Field: SUPPORTED ✅

The `.mcp.json` config **does** support a `headers` field for streamable-http transport:

```json
{
  "mcpServers": {
    "my-server": {
      "type": "streamable-http",
      "url": "http://host:9090/mcp",
      "headers": {
        "Authorization": "Bearer ${API_KEY}"
      }
    }
  }
}
```

### Environment Variable Expansion: SUPPORTED ✅

Claude Code supports environment variable expansion in headers:

- `${VAR}` - Direct variable substitution
- `${VAR:-default}` - Variable with fallback default

**Example:**

```json
{
  "mcpServers": {
    "api-server": {
      "type": "http",
      "url": "${API_BASE_URL:-https://api.example.com}/mcp",
      "headers": {
        "Authorization": "Bearer ${API_KEY}",
        "X-Custom-Header": "${CUSTOM_VALUE:-default}"
      }
    }
  }
}
```

### CLI Support

Headers can also be configured via CLI:

```bash
claude mcp add --transport http secure-api https://api.example.com/mcp \
  --header "Authorization: Bearer your-token"
```

### Real-World Examples

**Upsun MCP Server:**
```json
{
  "mcpServers": {
    "upsun": {
      "type": "streamable-http",
      "url": "https://mcp.upsun.com/mcp",
      "headers": {
        "upsun-api-token": "YOUR_API_TOKEN",
        "enable-write": "false"
      }
    }
  }
}
```

## 2. MCP Specification

### Bearer Token Standard

The MCP Authorization spec (draft) mandates:

**Client Requirements:**
- **MUST** use `Authorization: Bearer <token>` header
- **MUST NOT** include tokens in query strings
- **MUST** include `resource` parameter to prevent token misuse

**Server Requirements:**
- **MUST** validate token audience (intended recipient)
- **MUST** validate token expiry and scopes
- **MUST** respond with `401` for invalid tokens, `403` for insufficient scopes

### Discovery Mechanisms

Servers advertise their authorization servers via:

1. **WWW-Authenticate header** in 401 responses
2. **Well-known URIs** at `.well-known/oauth-protected-resource`

### Error Responses

| Status | Meaning | When |
|--------|---------|------|
| 401 | Unauthorized | Token missing, invalid, or expired |
| 403 | Forbidden | Valid token but insufficient scopes |
| 400 | Bad Request | Malformed authorization request |

**Example insufficient scope response:**

```http
HTTP/1.1 403 Forbidden
WWW-Authenticate: Bearer error="insufficient_scope",
                         scope="files:read files:write",
                         resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource"
```

## 3. FastMCP Server Support

### Authentication Middleware: SUPPORTED ✅

FastMCP provides multiple authentication approaches:

**1. Built-in OAuth 2.0/2.1:**
- Pre-configured providers (GitHub, etc.)
- Automatic token management
- JWT token issuance

**2. Custom Middleware:**

```python
from starlette.middleware import Middleware

@mcp.middleware("request")
async def auth_middleware(request):
    # Validate Authorization header
    auth = request.headers.get("Authorization")
    if not auth or not validate_token(auth):
        raise HTTPException(401, "Unauthorized")
    return request
```

**3. CORS Configuration:**

For browser-based clients, FastMCP requires proper CORS setup:

```python
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "mcp-protocol-version",
            "mcp-session-id",
            "Authorization",      # Required for auth
            "Content-Type",
        ],
        expose_headers=["mcp-session-id"],
    )
]

http_app = mcp.http_app(middleware=middleware)
```

**Critical:** Without `expose_headers=["mcp-session-id"]`, JavaScript can't access session IDs, breaking session management.

### Production Recommendations

FastMCP documentation emphasizes:
- **HTTPS required** for production
- **Token-based authentication** via API keys, OAuth, or JWT
- **Persistent storage** (e.g., Redis) for token management across instances
- **Explicit JWT signing keys** for multi-instance deployments

## Complete Flow Example

### Client Configuration (.mcp.json)

```json
{
  "mcpServers": {
    "my-api": {
      "type": "streamable-http",
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${MCP_API_TOKEN}"
      }
    }
  }
}
```

### Server Implementation (FastMCP)

```python
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

mcp = FastMCP("My API")

# Add authentication middleware
@mcp.middleware("request")
async def verify_bearer_token(request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")

    token = auth_header[7:]  # Remove "Bearer " prefix
    if not validate_token(token):
        raise HTTPException(403, "Invalid or expired token")

    return request

# Configure CORS if needed
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_headers=["Authorization", "Content-Type", "mcp-session-id"],
        expose_headers=["mcp-session-id"],
    )
]

# Start server
http_app = mcp.http_app(middleware=middleware)
```

### Request Flow

1. Client sends request with `Authorization: Bearer ${MCP_API_TOKEN}` header
2. Server CORS middleware validates origin and headers
3. Server auth middleware validates bearer token
4. If valid, request proceeds to MCP handler
5. If invalid, returns 401/403 with WWW-Authenticate header

## Security Best Practices

From the MCP spec and FastMCP docs:

1. **Token Audience Validation**: Servers must verify tokens were issued specifically for them
2. **HTTPS Required**: All production deployments must use TLS
3. **No Token Passthrough**: Servers must not forward client tokens to upstream APIs
4. **PKCE for OAuth**: Clients must implement PKCE (OAuth 2.1 requirement)
5. **Environment Variables**: Use `${VAR}` syntax for credentials, never hardcode
6. **Scope Minimization**: Request only necessary scopes, use step-up auth for additional permissions

## Conclusion

The MCP streamable-http transport has **full support** for authentication headers:

- ✅ **Client config**: `headers` field with environment variable expansion
- ✅ **MCP spec**: OAuth 2.1 with bearer tokens via Authorization header
- ✅ **Server implementation**: Middleware for token validation and CORS
- ✅ **Security**: Comprehensive token validation, audience binding, and scope management

The implementation is production-ready and follows OAuth 2.1 best practices.
