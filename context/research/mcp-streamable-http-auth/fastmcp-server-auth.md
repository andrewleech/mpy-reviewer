---
timestamp: 2026-02-23T00:00:00Z
research_topic: "MCP streamable-http transport authentication headers support"
query: "FastMCP streamable-http transport authentication middleware"
source_url: https://gofastmcp.com/deployment/http
source_name: FastMCP HTTP Deployment Documentation
relevance: High
---

## Source
[FastMCP HTTP Deployment](https://gofastmcp.com/deployment/http)

## Query Context
Understanding whether FastMCP's streamable-http server transport supports authentication middleware.

## Key Findings

### Authentication Support: YES

FastMCP provides robust authentication mechanisms for HTTP servers:

**Authentication Methods:**
- **Bearer tokens** - Simple token-based authentication
- **JWT** - JSON Web Tokens for stateless authentication
- **OAuth** - Full OAuth 2.0 support with providers like GitHub

**Recommendation:** Authentication is **highly recommended** for remote MCP servers. Some LLM clients require authentication and will refuse to connect without it.

### Middleware Capabilities

**Custom Middleware Support (since v2.3.2):**

FastMCP allows adding custom Starlette middleware to ASGI applications:

```python
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

http_app = mcp.http_app(middleware=middleware)
```

**Middleware Design:**
- FastMCP encourages separating auth logic into middleware
- Supports middleware decorators like `@mcp.middleware("request")`
- For Python implementations, can validate API keys from request headers

### CORS Configuration

**For browser-based MCP clients:**

FastMCP requires specific header configuration when JavaScript runs in a browser:

```python
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],  # Specify exact origins
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "mcp-protocol-version",
            "mcp-session-id",
            "Authorization",      # ← Critical for auth
            "Content-Type",
        ],
        expose_headers=["mcp-session-id"],  # Critical for session management
    )
]
```

**Important:** Without `expose_headers`, browsers receive the session ID but JavaScript can't access it, causing session management to fail.

### OAuth Implementation

**Production OAuth:**
- FastMCP handles token management automatically
- Can issue JWT tokens to clients rather than forwarding upstream provider tokens
- Maintains proper OAuth boundaries

**Production Requirements:**
- Implement explicit JWT signing keys
- Use persistent network-accessible storage (e.g., Redis) for token management
- Ensures tokens survive server restarts across multiple instances

### Session Management

FastMCP's Streamable HTTP transport maintains server-side sessions:
- Enables stateful MCP features
- Supports elicitation and sampling
- Maintains context across multiple requests from the same client

### Production Deployment Security

For production, FastMCP recommends:
- Serve over HTTPS to protect traffic and user sessions
- Add token-based authentication via API keys, OAuth, or JWT
- Use proper middleware for authentication validation

## Relevance Notes

FastMCP fully supports authentication for streamable-http transport through:
1. Built-in OAuth 2.0/2.1 support
2. Custom middleware capabilities
3. Bearer token validation
4. JWT token management
5. Proper CORS configuration for web clients

Server authors can implement authentication by:
- Using built-in OAuth providers
- Writing custom middleware to validate Authorization headers
- Configuring CORS to allow Authorization headers from browser clients
