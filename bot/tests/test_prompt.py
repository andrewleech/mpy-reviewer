"""Tests for bot.prompt."""

from bot.prompt import build_system_prompt, build_user_message


def test_system_prompt_includes_style_guide():
    prompt = build_system_prompt()
    assert "dpgeorge Review Style" in prompt


def test_system_prompt_includes_security_section():
    prompt = build_system_prompt()
    assert "Security" in prompt
    assert "untrusted-pr-content" in prompt


def test_system_prompt_includes_additional_prompt():
    prompt = build_system_prompt(additional_system_prompt="Extra instructions here")
    assert "Extra instructions here" in prompt


def test_user_message_wraps_in_untrusted_delimiters():
    msg = build_user_message(
        diff_text="diff content",
        pr_number=1,
        pr_title="Test PR",
        pr_body="body",
        repo_owner="micropython",
        repo_name="micropython",
    )
    assert "<untrusted-pr-content>" in msg
    assert "</untrusted-pr-content>" in msg


def test_user_message_includes_head_sha():
    msg = build_user_message(
        diff_text="diff",
        pr_number=1,
        pr_title="T",
        pr_body="B",
        repo_owner="o",
        repo_name="r",
        head_sha="abc123",
    )
    assert "abc123" in msg


def test_user_message_handles_empty_body():
    msg = build_user_message(
        diff_text="diff",
        pr_number=1,
        pr_title="T",
        pr_body="",
        repo_owner="o",
        repo_name="r",
    )
    assert "Description:" not in msg
    assert "<untrusted-pr-content>" in msg
