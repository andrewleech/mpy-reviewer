# Stage 1: Build codanna from Rust
FROM rust:1.88-slim AS codanna-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev perl make g++ && \
    rm -rf /var/lib/apt/lists/*
RUN cargo install codanna --all-features

# Stage 2: Node.js (for Claude CLI)
FROM node:22-slim AS node-source

# Stage 3: Runtime
FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Node.js from official image
COPY --from=node-source /usr/local/bin/node /usr/local/bin/node
COPY --from=node-source /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Copy codanna from builder stage
COPY --from=codanna-builder /usr/local/cargo/bin/codanna /usr/local/bin/codanna

# Create non-root user
RUN useradd -m -s /bin/bash botuser

WORKDIR /app

# Copy source and install (non-editable, with bot extras)
COPY pyproject.toml ./
COPY rag/ rag/
COPY bot/ bot/
COPY mcp_server.py .
COPY data/reviews.db data/

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir ".[bot]"

# Copy entrypoint
COPY bot/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Prepare volume mount points with correct ownership
RUN mkdir -p /workspace/micropython /config /var/run/token /home/botuser/.cache/huggingface && \
    chown botuser:botuser /workspace/micropython /config /var/run/token /home/botuser/.cache/huggingface

VOLUME ["/workspace/micropython", "/config"]
ENV GITHUB_TOKEN_FILE=/var/run/token/github_token
ENV MPY_CHECKOUT=/workspace/micropython

# Switch to non-root user
RUN chown -R botuser:botuser /app
USER botuser

ENTRYPOINT ["/entrypoint.sh"]
