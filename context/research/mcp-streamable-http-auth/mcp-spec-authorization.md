---
timestamp: 2026-02-23T00:00:00Z
research_topic: "MCP streamable-http transport authentication headers support"
query: "MCP specification HTTP transport authentication bearer token"
source_url: https://modelcontextprotocol.io/specification/draft/basic/authorization
source_name: MCP Authorization Specification (Draft)
relevance: High
---

## Source
[MCP Authorization Specification](https://modelcontextprotocol.io/specification/draft/basic/authorization)

## Query Context
Understanding what the MCP specification says about HTTP transport authentication and bearer tokens.

## Key Findings

### Bearer Token Authentication

The MCP spec defines **OAuth 2.1-based authorization** for HTTP transports:

**Client Requirements:**
- MCP clients **MUST** use the Authorization request header field
- Format: `Authorization: Bearer <access-token>`
- Access tokens **MUST NOT** be included in the URI query string

**Example request:**

```http
GET /mcp HTTP/1.1
Host: mcp.example.com
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### Server Validation Requirements

**MCP servers MUST:**
1. Validate access tokens as described in OAuth 2.1 Section 5.2
2. Validate that tokens were issued specifically for them as the intended audience (via `resource` parameter / RFC 8707)
3. Respond with `HTTP 401` for invalid or expired tokens
4. Respond with `HTTP 403` for insufficient scopes

### Authorization Discovery

**Protected Resource Metadata Discovery:**

MCP servers **MUST** implement OAuth 2.0 Protected Resource Metadata (RFC9728) to advertise their authorization servers.

Two discovery mechanisms:

1. **WWW-Authenticate Header**: In 401 responses
   ```http
   HTTP/1.1 401 Unauthorized
   WWW-Authenticate: Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource",
                            scope="files:read"
   ```

2. **Well-Known URI**: At `.well-known/oauth-protected-resource/[path]` or `.well-known/oauth-protected-resource`

### Resource Parameter (RFC 8707)

MCP clients **MUST** implement Resource Indicators for OAuth 2.0:

- Include `resource` parameter in authorization and token requests
- `resource` identifies the MCP server the token is intended for
- Example: `&resource=https%3A%2F%2Fmcp.example.com`

This prevents token misuse across different services (confused deputy attacks).

### Error Handling

| Status Code | Description  | Usage                                      |
|-------------|--------------|-------------------------------------------|
| 401         | Unauthorized | Authorization required or token invalid   |
| 403         | Forbidden    | Invalid scopes or insufficient permissions|
| 400         | Bad Request  | Malformed authorization request           |

**Insufficient scope response:**

```http
HTTP/1.1 403 Forbidden
WWW-Authenticate: Bearer error="insufficient_scope",
                         scope="files:read files:write user:profile",
                         resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource",
                         error_description="Additional file write permission required"
```

### Client Registration

MCP supports three registration mechanisms (priority order):

1. **Client ID Metadata Documents** - HTTPS URLs as client identifiers (most common, no prior relationship needed)
2. **Pre-registration** - Static client credentials from server's developer portal
3. **Dynamic Client Registration (RFC7591)** - For backwards compatibility

### Security Considerations

**Token Audience Binding:**
- MCP clients **MUST** include the `resource` parameter
- MCP servers **MUST** validate tokens were issued specifically for them
- Token passthrough to upstream APIs is **explicitly forbidden**

**Authorization Code Protection:**
- MCP clients **MUST** implement PKCE (OAuth 2.1)
- **MUST** verify PKCE support via `code_challenge_methods_supported` in server metadata
- **MUST** use `S256` code challenge method

**Communication Security:**
- All authorization server endpoints **MUST** be HTTPS
- All redirect URIs **MUST** be `localhost` or use HTTPS

## Relevance Notes

The MCP specification defines a comprehensive OAuth 2.1-based authorization framework for HTTP transports. While it doesn't explicitly document client configuration file formats (that's implementation-specific), it mandates that:

1. Clients must send bearer tokens via `Authorization` header
2. Servers must validate token audience
3. OAuth discovery and metadata are standardized

The spec focuses on the protocol flow, not client configuration formats like `.mcp.json` - those are defined by MCP client implementations (like Claude Code).
