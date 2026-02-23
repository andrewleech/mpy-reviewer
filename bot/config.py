"""TOML configuration loader for the GitHub review bot."""

import dataclasses
import logging
import os
import tomllib
import types
import typing
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class GitHubAppConfig:
    app_id: int = 0
    private_key: str = ""
    private_key_path: str = ""
    webhook_secret: str = ""
    installation_id: int = 0

    def get_private_key_pem(self) -> str:
        """Return the PEM key, reading from file if needed."""
        if self.private_key:
            return self.private_key
        if self.private_key_path:
            try:
                return Path(self.private_key_path).read_text()
            except (FileNotFoundError, PermissionError) as e:
                raise ValueError(
                    f"Cannot read private key from {self.private_key_path}: {e}"
                ) from e
        raise ValueError("No private key configured (set private_key or private_key_path)")


@dataclass
class TargetConfig:
    repo: str = "micropython/micropython"

    def __post_init__(self):
        if "/" not in self.repo:
            raise ValueError(f"repo must be 'owner/name', got: {self.repo!r}")
        owner, name = self.repo.split("/", 1)
        if not owner or not name:
            raise ValueError(f"repo must be 'owner/name', got: {self.repo!r}")

    @property
    def owner(self) -> str:
        return self.repo.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.repo.split("/", 1)[1]


@dataclass
class AuthConfig:
    claude_oauth_path: str = ""


@dataclass
class AuthorizationConfig:
    allowlist: list[str] = field(default_factory=list)


@dataclass
class ReviewConfig:
    model: str = "sonnet"
    timeout_seconds: int = 600
    top_k: int = 8
    include_codebase: bool = True


@dataclass
class PromptConfig:
    additional_system_prompt: str = ""


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class McpConfig:
    host: str = "mcp-server"
    port: int = 9090

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass
class BotConfig:
    github_app: GitHubAppConfig = field(default_factory=GitHubAppConfig)
    target: TargetConfig = field(default_factory=TargetConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    authorization: AuthorizationConfig = field(default_factory=AuthorizationConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    mcp: McpConfig = field(default_factory=McpConfig)

    def __post_init__(self):
        if self.github_app.app_id == 0:
            raise ValueError("github_app.app_id must be set")
        if not self.github_app.webhook_secret:
            raise ValueError("github_app.webhook_secret must be set")
        if self.github_app.installation_id == 0:
            raise ValueError("github_app.installation_id must be set")
        # Validate that at least one key source is configured
        if not self.github_app.private_key and not self.github_app.private_key_path:
            raise ValueError(
                "github_app: set private_key or private_key_path"
            )
        if self.github_app.private_key and not self.github_app.private_key_path:
            logger.debug(
                "Using inline private_key. Consider private_key_path for production."
            )


def _build_nested_dataclass(cls, data: dict):
    """Recursively build a dataclass from a dict, logging unknown keys.

    Note: does not handle generic containers (e.g. list[SomeDataclass]).
    Current config schema has no such fields.
    """
    if not dataclasses.is_dataclass(cls):
        return data
    field_names = {f.name for f in dataclasses.fields(cls)}
    hints = typing.get_type_hints(cls)
    filtered = {}
    for k, v in data.items():
        if k not in field_names:
            logger.warning("Unknown config key %r in %s", k, cls.__name__)
            continue
        hint = hints[k]
        # Unwrap Optional[X] / X | None to get the inner type
        origin = typing.get_origin(hint)
        if origin is typing.Union or origin is types.UnionType:
            args = [a for a in typing.get_args(hint) if a is not type(None)]
            if len(args) == 1:
                hint = args[0]
        if dataclasses.is_dataclass(hint):
            if isinstance(v, dict):
                filtered[k] = _build_nested_dataclass(hint, v)
            else:
                raise ValueError(
                    f"Expected dict for {cls.__name__}.{k}, got {type(v).__name__}"
                )
        else:
            filtered[k] = v
    return cls(**filtered)


def load_config(path: str | Path | None = None) -> BotConfig:
    """Load BotConfig from a TOML file.

    Args:
        path: Path to TOML config file. If None, reads from
              BOT_CONFIG_PATH env var, defaulting to /config/bot.toml.
    """
    if path is None:
        path = os.environ.get("BOT_CONFIG_PATH", "/config/bot.toml")
    path = Path(path)

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    return _build_config(raw)


def _build_config(raw: dict) -> BotConfig:
    """Build BotConfig from parsed TOML dict."""
    return _build_nested_dataclass(BotConfig, raw)


# Singleton
_bot_config: BotConfig | None = None


def get_bot_config() -> BotConfig:
    """Get the global bot config singleton."""
    global _bot_config
    if _bot_config is None:
        _bot_config = load_config()
    return _bot_config


def set_bot_config(config: BotConfig) -> None:
    """Set the global bot config singleton (for testing)."""
    global _bot_config
    _bot_config = config
