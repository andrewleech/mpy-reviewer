---
timestamp: 2026-02-23T00:00:00Z
research_topic: "MCP streamable-http transport authentication headers support"
query: "Claude Code .mcp.json streamable-http headers configuration"
source_url: https://code.claude.com/docs/en/mcp
source_name: Claude Code Documentation - MCP
relevance: High
---

## Source
[Claude Code MCP Documentation](https://code.claude.com/docs/en/mcp)

## Query Context
Investigating whether Claude Code's MCP client configuration supports custom headers (specifically Authorization bearer tokens) for streamable-http transport type.

## Key Findings

### Headers Support: YES

Claude Code **DOES** support custom headers in `.mcp.json` for streamable-http transport.

**Configuration format:**

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

### Environment Variable Expansion

Claude Code supports environment variable expansion in `.mcp.json` files:

**Supported syntax:**
- `${VAR}` - Expands to the value of environment variable `VAR`
- `${VAR:-default}` - Expands to `VAR` if set, otherwise uses `default`

**Expansion locations:**
- `command` - The server executable path
- `args` - Command-line arguments
- `env` - Environment variables passed to the server
- `url` - For HTTP server types
- **`headers`** - For HTTP server authentication ✅

**Example with environment variables:**

```json
{
  "mcpServers": {
    "api-server": {
      "type": "http",
      "url": "${API_BASE_URL:-https://api.example.com}/mcp",
      "headers": {
        "Authorization": "Bearer ${API_KEY}"
      }
    }
  }
}
```

### CLI Header Support

Headers can also be configured via CLI:

```bash
# Add HTTP server with Bearer token
claude mcp add --transport http secure-api https://api.example.com/mcp \
  --header "Authorization: Bearer your-token"

# Add SSE server with custom header
claude mcp add --transport sse private-api https://api.company.com/sse \
  --header "X-API-Key: your-key-here"
```

### Real-World Example

The Upsun MCP Server documentation shows actual usage:

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

## Relevance Notes

This confirms that Claude Code's MCP client fully supports custom headers for authentication with streamable-http transport. The `headers` field is a first-class configuration option that supports environment variable expansion for secure credential management.
