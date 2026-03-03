"""Tests for rag.verifier."""

import asyncio
import json
import os
import tempfile
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from rag.verifier import (
    build_verification_system_prompt,
    build_verification_user_message,
    run_single_verification,
    verify_all_findings,
    write_verdict_file,
    build_verification_orchestration_prompt,
    _validate_verdict,
    _cleanup_stale_tmpdirs,
    VERIFICATION_TIMEOUT,
    VERDICT_SCHEMA,
    MAX_FINDINGS,
)


def _make_finding(**overrides):
    """Create a finding dict with defaults."""
    finding = {
        "file": "py/gc.c",
        "line": 42,
        "severity": "blocking",
        "description": "Missing null check on gc_alloc return.",
        "diff_hunk": "+    void *ptr = gc_alloc(size);\n+    ptr->data = val;",
    }
    finding.update(overrides)
    return finding


def _make_verdict(index=0, verdict="confirmed", **overrides):
    """Create a verdict dict with defaults."""
    v = {
        "finding_index": index,
        "verdict": verdict,
        "evidence": "Found 3 similar patterns that include null checks.",
        "adjusted_severity": None,
        "confidence": "high",
    }
    v.update(overrides)
    return v


def _make_claude_output(structured_output):
    """Create the JSON output format that claude -p --json-schema produces."""
    return json.dumps({
        "type": "result",
        "structured_output": structured_output,
        "result": "",
    })


# --- build_verification_system_prompt ---

def test_build_verification_system_prompt_contains_dimensions():
    prompt = build_verification_system_prompt()
    assert "Convention Check" in prompt
    assert "Impact Trace" in prompt
    assert "Factual Verification" in prompt
    assert "Severity Calibration" in prompt


def test_build_verification_system_prompt_neutrality():
    prompt = build_verification_system_prompt()
    assert "Do not argue for or against" in prompt


def test_build_verification_system_prompt_codanna_instructions():
    prompt = build_verification_system_prompt()
    assert "codanna semantic_search" in prompt
    assert "codanna find_symbol" in prompt
    assert "codanna find_callers" in prompt
    assert "codanna analyze_impact" in prompt


# --- build_verification_user_message ---

def test_build_verification_user_message_contains_finding():
    finding = _make_finding()
    msg = build_verification_user_message(finding, 0, "diff text", [])
    assert "py/gc.c" in msg
    assert "42" in msg
    assert "blocking" in msg
    assert "Missing null check" in msg


def test_build_verification_user_message_includes_diff():
    finding = _make_finding()
    diff = "diff --git a/py/gc.c b/py/gc.c\n+new line"
    msg = build_verification_user_message(finding, 0, diff, [])
    assert "diff --git" in msg


def test_build_verification_user_message_includes_search_results():
    finding = _make_finding()
    results = [
        {"body": "This is precedent.", "severity": "blocking", "domain": "correctness", "path": "py/gc.c"},
    ]
    msg = build_verification_user_message(finding, 0, "diff", results)
    assert "Historical Review Precedent" in msg
    assert "This is precedent." in msg


def test_build_verification_user_message_includes_pr_metadata():
    finding = _make_finding()
    msg = build_verification_user_message(finding, 0, "diff", [], pr_number=12345, repo="micropython/micropython")
    assert "#12345" in msg
    assert "micropython/micropython" in msg


# --- run_single_verification ---

@pytest.mark.asyncio
async def test_run_single_verification_success():
    """Mock subprocess returning valid structured output."""
    verdict = _make_verdict(0)
    stdout = _make_claude_output(verdict).encode()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    async def communicate(input=None):
        return stdout, b""
    mock_proc.communicate = communicate

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await run_single_verification(
            _make_finding(), 0, "diff", [],
            build_verification_system_prompt(),
        )

    assert result["verdict"] == "confirmed"
    assert result["finding_index"] == 0
    assert result["confidence"] == "high"


@pytest.mark.asyncio
async def test_run_single_verification_timeout():
    """Mock a hanging subprocess — should return inconclusive."""
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    async def hang(input=None):
        await asyncio.sleep(100)
    mock_proc.communicate = hang

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("rag.verifier.VERIFICATION_TIMEOUT", 0.01):
            result = await run_single_verification(
                _make_finding(), 0, "diff", [],
                build_verification_system_prompt(),
            )

    assert result["verdict"] == "inconclusive"
    assert "timed out" in result["evidence"]


@pytest.mark.asyncio
async def test_run_single_verification_crash():
    """Non-zero exit code returns inconclusive."""
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    async def communicate(input=None):
        return b"", b"error occurred"
    mock_proc.communicate = communicate

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await run_single_verification(
            _make_finding(), 0, "diff", [],
            build_verification_system_prompt(),
        )

    assert result["verdict"] == "inconclusive"
    assert "exited with code 1" in result["evidence"]


@pytest.mark.asyncio
async def test_run_single_verification_bad_json():
    """Invalid JSON stdout returns inconclusive."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    async def communicate(input=None):
        return b"not json at all", b""
    mock_proc.communicate = communicate

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await run_single_verification(
            _make_finding(), 0, "diff", [],
            build_verification_system_prompt(),
        )

    assert result["verdict"] == "inconclusive"
    assert "invalid JSON" in result["evidence"]


# --- verify_all_findings ---

@pytest.mark.asyncio
async def test_verify_all_findings_parallel():
    """Verify that multiple findings are processed and all return verdicts."""
    findings = [_make_finding(file=f"file{i}.c") for i in range(3)]

    verdict_template = _make_verdict()
    stdout = _make_claude_output(verdict_template).encode()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    async def communicate(input=None):
        return stdout, b""
    mock_proc.communicate = communicate

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("shutil.which", return_value="/usr/bin/claude"):
            prompt, file_infos = await verify_all_findings(
                findings, "diff text",
            )

    assert len(file_infos) == 3
    assert "confirmed" in prompt
    # All verdict files should exist
    for info in file_infos:
        assert os.path.exists(info["path"])
    # Clean up
    for info in file_infos:
        os.unlink(info["path"])
    os.rmdir(os.path.dirname(file_infos[0]["path"]))


@pytest.mark.asyncio
async def test_verify_all_findings_empty():
    """Empty findings list returns immediately."""
    prompt, file_infos = await verify_all_findings([], "diff")
    assert file_infos == []
    assert "No findings to verify" in prompt


@pytest.mark.asyncio
async def test_verify_all_findings_no_claude():
    """Missing claude binary returns error."""
    with patch("shutil.which", return_value=None):
        prompt, file_infos = await verify_all_findings(
            [_make_finding()], "diff",
        )
    assert file_infos == []
    assert "not found" in prompt


# --- write_verdict_file ---

def test_write_verdict_file_format():
    """Verify markdown structure of verdict files."""
    with tempfile.TemporaryDirectory(prefix="mpy-verify-test-") as tmp:
        finding = _make_finding()
        verdict = _make_verdict(0, "confirmed", evidence="Found matching patterns.")

        info = write_verdict_file(tmp, finding, verdict)

        assert info["verdict"] == "confirmed"
        assert info["finding_index"] == 0
        assert info["original_severity"] == "blocking"
        assert os.path.exists(info["path"])
        assert info["path"].endswith("finding-0-confirmed.md")

        content = open(info["path"]).read()
        assert "# Finding #0: confirmed" in content
        assert "py/gc.c" in content
        assert "Found matching patterns." in content
        assert "blocking" in content


# --- build_verification_orchestration_prompt ---

def test_build_verification_orchestration_prompt_table():
    """Verify table columns and summary counts."""
    file_infos = [
        {"finding_index": 0, "path": "/tmp/f0.md", "original_severity": "blocking",
         "verdict": "confirmed", "adjusted_severity": None, "confidence": "high"},
        {"finding_index": 1, "path": "/tmp/f1.md", "original_severity": "suggestion",
         "verdict": "false_positive", "adjusted_severity": None, "confidence": "high"},
        {"finding_index": 2, "path": "/tmp/f2.md", "original_severity": "blocking",
         "verdict": "partially_valid", "adjusted_severity": "suggestion", "confidence": "medium"},
    ]

    prompt = build_verification_orchestration_prompt(file_infos)

    assert "1 confirmed" in prompt
    assert "1 false_positive" in prompt
    assert "1 partially_valid" in prompt
    assert "| # | File | Original Severity | Verdict | Adjusted | Confidence |" in prompt
    # Table rows
    assert "confirmed" in prompt
    assert "false_positive" in prompt
    assert "partially_valid" in prompt


def test_build_verification_orchestration_prompt_empty():
    prompt = build_verification_orchestration_prompt([])
    assert "No findings were verified" in prompt


# --- _validate_verdict ---

def test_validate_verdict_valid():
    v = _make_verdict(0)
    assert _validate_verdict(v, 0) is v


def test_validate_verdict_missing_keys():
    assert _validate_verdict({"verdict": "confirmed"}, 0) is None


def test_validate_verdict_invalid_verdict_value():
    v = _make_verdict(0, verdict="INVALID")
    assert _validate_verdict(v, 0) is None


def test_validate_verdict_not_dict():
    assert _validate_verdict("string", 0) is None


# --- run_single_verification with result string fallback ---

@pytest.mark.asyncio
async def test_run_single_verification_result_string_fallback():
    """Test the result-as-JSON-string fallback path."""
    verdict = _make_verdict(0, verdict="false_positive")
    output = json.dumps({
        "type": "result",
        "structured_output": None,
        "result": json.dumps(verdict),
    })

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    async def communicate(input=None):
        return output.encode(), b""
    mock_proc.communicate = communicate

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await run_single_verification(
            _make_finding(), 0, "diff", [],
            build_verification_system_prompt(),
        )

    assert result["verdict"] == "false_positive"


@pytest.mark.asyncio
async def test_run_single_verification_malformed_verdict():
    """Agent returns JSON that doesn't match verdict schema."""
    bad_output = json.dumps({
        "type": "result",
        "structured_output": {"some_other_field": "value"},
        "result": "",
    })

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    async def communicate(input=None):
        return bad_output.encode(), b""
    mock_proc.communicate = communicate

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await run_single_verification(
            _make_finding(), 0, "diff", [],
            build_verification_system_prompt(),
        )

    assert result["verdict"] == "inconclusive"
    assert "malformed" in result["evidence"]


# --- verify_all_findings with retriever ---

@pytest.mark.asyncio
async def test_verify_all_findings_with_retriever():
    """Verify pre-fetch path exercises the retriever."""
    findings = [_make_finding()]

    verdict = _make_verdict(0)
    stdout = _make_claude_output(verdict).encode()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    async def communicate(input=None):
        return stdout, b""
    mock_proc.communicate = communicate

    mock_retriever = MagicMock()
    mock_retriever.search_with_filters.return_value = [
        {"body": "precedent", "severity": "blocking", "domain": "correctness"},
    ]

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("shutil.which", return_value="/usr/bin/claude"):
            prompt, file_infos = await verify_all_findings(
                findings, "diff text", retriever=mock_retriever,
            )

    assert len(file_infos) == 1
    mock_retriever.search_with_filters.assert_called_once()
    # Clean up
    for info in file_infos:
        os.unlink(info["path"])
    os.rmdir(os.path.dirname(file_infos[0]["path"]))


# --- verify_all_findings with gather exception ---

@pytest.mark.asyncio
async def test_verify_all_findings_gather_exception():
    """When a verification coroutine raises, it becomes inconclusive."""
    findings = [_make_finding()]

    async def raise_error(*args, **kwargs):
        raise RuntimeError("subprocess failed")

    with patch("rag.verifier.run_single_verification", side_effect=raise_error):
        with patch("shutil.which", return_value="/usr/bin/claude"):
            prompt, file_infos = await verify_all_findings(
                findings, "diff text",
            )

    assert len(file_infos) == 1
    assert file_infos[0]["verdict"] == "inconclusive"
    assert "error" in file_infos[0]["path"].lower() or "inconclusive" in file_infos[0]["path"]
    # Clean up
    for info in file_infos:
        os.unlink(info["path"])
    os.rmdir(os.path.dirname(file_infos[0]["path"]))


# --- write_verdict_file with path-traversal verdict type ---

def test_write_verdict_file_sanitizes_verdict_type():
    """Verdict types with special characters are sanitized in filename."""
    with tempfile.TemporaryDirectory(prefix="mpy-verify-test-") as tmp:
        finding = _make_finding()
        verdict = _make_verdict(0, verdict="../../etc/passwd")

        info = write_verdict_file(tmp, finding, verdict)

        # Filename should have special chars stripped
        filename = os.path.basename(info["path"])
        assert "/" not in filename
        assert ".." not in filename


# --- _cleanup_stale_tmpdirs ---

def test_cleanup_stale_tmpdirs():
    """Old mpy-verify-* dirs are removed."""
    with tempfile.TemporaryDirectory() as base:
        stale = os.path.join(base, "mpy-verify-old")
        os.makedirs(stale)
        # Backdate mtime
        old_time = time.time() - 7200  # 2 hours ago
        os.utime(stale, (old_time, old_time))

        fresh = os.path.join(base, "mpy-verify-new")
        os.makedirs(fresh)

        _cleanup_stale_tmpdirs(base)

        assert not os.path.exists(stale)
        assert os.path.exists(fresh)
