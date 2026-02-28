"""Tests for bot.config."""

import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

import pytest

from bot.config import (
    _build_nested_dataclass, _build_config, BotConfig, TargetConfig, GitHubAppConfig,
    load_config, get_bot_config, set_bot_config,
)
import bot.config as config_module


@dataclass
class Inner:
    x: int = 0
    y: str = ""


@dataclass
class Outer:
    name: str = ""
    inner: Inner = None

    def __post_init__(self):
        if self.inner is None:
            self.inner = Inner()


def test_build_nested_dataclass_simple():
    result = _build_nested_dataclass(Inner, {"x": 42, "y": "hello"})
    assert result.x == 42
    assert result.y == "hello"


def test_build_nested_dataclass_unknown_keys(caplog):
    with caplog.at_level(logging.WARNING):
        result = _build_nested_dataclass(Inner, {"x": 1, "bogus": "ignored"})
    assert result.x == 1
    assert any("Unknown config key 'bogus'" in msg for msg in caplog.messages)


def test_build_nested_dataclass_nested():
    data = {"name": "test", "inner": {"x": 10, "y": "nested"}}
    result = _build_nested_dataclass(Outer, data)
    assert result.name == "test"
    assert result.inner.x == 10
    assert result.inner.y == "nested"


def _minimal_config() -> dict:
    return {
        "github_app": {
            "app_id": 12345,
            "webhook_secret": "s3cret",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
        }
    }


def test_build_config_minimal():
    cfg = _build_config(_minimal_config())
    assert isinstance(cfg, BotConfig)
    assert cfg.github_app.app_id == 12345
    assert cfg.github_app.webhook_secret == "s3cret"


def test_bot_config_validates_app_id():
    raw = _minimal_config()
    raw["github_app"]["app_id"] = 0
    with pytest.raises(ValueError, match="app_id"):
        _build_config(raw)


def test_bot_config_validates_webhook_secret():
    raw = _minimal_config()
    raw["github_app"]["webhook_secret"] = ""
    with pytest.raises(ValueError, match="webhook_secret"):
        _build_config(raw)


def test_target_config_validates_repo_format():
    with pytest.raises(ValueError, match="owner/name"):
        TargetConfig(repos=["noslash"])


def test_target_config_valid_repos():
    tc = TargetConfig(repos=["owner/name", "other/repo"])
    assert tc.accepts("owner/name")
    assert tc.accepts("other/repo")
    assert not tc.accepts("unknown/repo")


def test_target_config_back_compat_single_string():
    """Old-style `repo = "owner/name"` is wrapped into a list."""
    raw = _minimal_config()
    raw["target"] = {"repo": "owner/name"}
    cfg = _build_config(raw)
    assert cfg.target.repos == ["owner/name"]
    assert cfg.target.accepts("owner/name")


def test_build_nested_optional_field():
    @dataclass
    class OptOuter:
        inner: Optional[Inner] = None

        def __post_init__(self):
            if self.inner is None:
                self.inner = Inner()

    result = _build_nested_dataclass(OptOuter, {"inner": {"x": 5, "y": "opt"}})
    assert result.inner.x == 5
    assert result.inner.y == "opt"


def test_build_nested_pep604_union():
    @dataclass
    class PepOuter:
        inner: Inner | None = None

        def __post_init__(self):
            if self.inner is None:
                self.inner = Inner()

    result = _build_nested_dataclass(PepOuter, {"inner": {"x": 7, "y": "pep604"}})
    assert result.inner.x == 7
    assert result.inner.y == "pep604"


def test_get_private_key_pem_missing_file():
    cfg = GitHubAppConfig(private_key_path="/nonexistent/path/key.pem")
    with pytest.raises(ValueError, match="/nonexistent/path/key.pem"):
        cfg.get_private_key_pem()


def test_build_nested_non_dict_raises():
    with pytest.raises(ValueError, match="Expected dict"):
        _build_nested_dataclass(Outer, {"name": "x", "inner": "not-a-dict"})


def test_load_config_from_toml_file():
    toml_content = b"""
[github_app]
app_id = 99
webhook_secret = "sec"
private_key = "-----BEGIN RSA PRIVATE KEY-----\\nfake\\n-----END RSA PRIVATE KEY-----"
"""
    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        f.write(toml_content)
        path = f.name
    try:
        cfg = load_config(path)
        assert cfg.github_app.app_id == 99
    finally:
        os.unlink(path)


def test_singleton_lifecycle():
    original = config_module._bot_config
    try:
        cfg = _build_config(_minimal_config())
        set_bot_config(cfg)
        assert get_bot_config() is cfg
    finally:
        config_module._bot_config = original
