# Review Bot

GitHub App that reviews MicroPython pull requests on demand. Users trigger a review by commenting `/review` on a PR or requesting review from the bot via the GitHub UI.

## Adding a Fork

The bot can serve multiple repositories simultaneously. Each fork uses its own GitHub App installation for authentication.

### Prerequisites

- The bot is already deployed and serving the primary repo
- The fork owner has admin access to their fork

### Steps

**1. Install the GitHub App on the fork**

The fork owner visits the App's installation page:

```
https://github.com/apps/mpy-reviewer/installations/new
```

Select the fork repository and grant the required permissions (pull requests, issues, checks).

**2. Configure the webhook**

In the fork's repo settings (Settings > Webhooks), add a webhook pointing to the bot:

- **Payload URL:** `https://<bot-host>:<port>/webhook`
- **Content type:** `application/json`
- **Secret:** Same `webhook_secret` as in `bot.toml`
- **Events:** Select "Issue comments" and "Pull requests"

Alternatively, if the GitHub App is configured with a webhook URL at the app level, it already receives events from all installations. In that case, skip this step.

**3. Add the fork to `bot.toml`**

```toml
[target]
repos = ["micropython/micropython", "contributor/micropython"]
```

**4. Restart the webhook container**

```bash
docker compose -f bot/docker-compose.yml restart webhook
```

The MCP server container also reads `bot.toml` and must be restarted if it was already running:

```bash
docker compose -f bot/docker-compose.yml restart mcp-server
```

Or restart both:

```bash
docker compose -f bot/docker-compose.yml up -d
```

### How it works

- The bot extracts `installation.id` from each webhook payload
- Each installation gets its own cached authentication token
- The `[target] repos` list acts as an allowlist -- webhooks from unlisted repos are ignored
- The `[authorization] allowlist` applies across all repos; collaborators with write access are always authorized regardless of repo

### Removing a fork

Remove the repo from `[target] repos` in `bot.toml` and restart. The GitHub App installation can be uninstalled from the fork's settings independently.
