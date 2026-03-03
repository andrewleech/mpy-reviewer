"""Cross-review verification engine.

Spawns parallel claude -p subprocesses to verify review findings against the
actual codebase using codanna, filesystem access, and the review database.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile

logger = logging.getLogger(__name__)

VERIFICATION_TIMEOUT = 300
VERIFICATION_MODEL = "sonnet"
MAX_BUDGET_USD = "0.50"

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "finding_index": {"type": "integer"},
        "verdict": {
            "type": "string",
            "enum": ["confirmed", "partially_valid", "false_positive", "inconclusive"],
        },
        "evidence": {"type": "string"},
        "adjusted_severity": {
            "type": ["string", "null"],
            "enum": ["blocking", "suggestion", "nitpick", None],
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
    },
    "required": ["finding_index", "verdict", "evidence", "adjusted_severity", "confidence"],
}

REQUIRED_FINDING_FIELDS = ("file", "line", "severity", "description", "diff_hunk")


def build_verification_system_prompt() -> str:
    """Build the system prompt for a verification agent."""
    return """You are a code review verification agent. Your job is to gather evidence \
about a review finding and determine whether it is valid.

You have access to: Bash (for codanna CLI and gh CLI), Read, Glob, Grep.

## Codanna CLI

Use the codanna CLI for semantic code search and symbol analysis:
- `codanna semantic_search "query"` — search codebase for semantically similar code
- `codanna find_symbol "name"` — find definition of a symbol
- `codanna find_callers "name"` — find all callers of a function/method
- `codanna analyze_impact "name"` — analyze impact of changes to a symbol

## Verification Dimensions

Perform these checks as applicable to the finding:

### 1. Convention Check
Search the codebase for patterns similar to what the finding criticizes. If the \
"problematic" pattern is used consistently elsewhere in the project, the finding \
is likely a false positive (it matches established project convention).

Use: codanna semantic_search, Glob, Grep.

### 2. Impact Trace
For correctness or logic findings, trace the actual code path to verify the claim \
applies. Can this code path actually be reached? Does the condition the finding \
describes actually occur?

Use: codanna find_callers, find_symbol, Read.

### 3. Factual Verification
For claims about platform behavior, API availability, header definitions, or \
external specifications, verify that the claim is factually accurate.

Use: gh CLI, Read (header files, docs), Grep.

### 4. Severity Calibration
After the above checks, reassess whether the original severity is appropriate \
given the evidence gathered. A finding might be technically valid but over-stated \
(blocking when it should be a suggestion), or under-stated.

## Neutrality

Do not argue for or against the finding. Gather evidence and report what you find. \
If evidence is mixed, say so.

## Output

Output ONLY a JSON object matching the provided schema. Do not include any text \
before or after the JSON."""


def build_verification_user_message(
    finding: dict,
    finding_index: int,
    diff_text: str,
    search_results: list,
    pr_number: int | None = None,
    repo: str = "micropython/micropython",
) -> str:
    """Build the user message for a single verification agent."""
    lines = [
        f"# Finding #{finding_index} to Verify",
        "",
        f"- **File:** `{finding['file']}`",
        f"- **Line:** {finding['line']}",
        f"- **Severity:** {finding['severity']}",
        f"- **Description:** {finding['description']}",
    ]

    if finding.get("diff_hunk"):
        lines.extend([
            "",
            "## Relevant Diff Hunk",
            "```diff",
            finding["diff_hunk"],
            "```",
        ])

    if pr_number:
        lines.extend(["", f"PR: #{pr_number} on {repo}"])

    lines.extend([
        "",
        "## Full Diff Context",
        "```diff",
        diff_text[:50000] if len(diff_text) > 50000 else diff_text,
        "```",
    ])

    if search_results:
        lines.extend(["", "## Historical Review Precedent", ""])
        for i, result in enumerate(search_results[:5], 1):
            body = result.get("body", "")
            if len(body) > 500:
                body = body[:500] + "..."
            severity = result.get("severity", "?")
            domain = result.get("domain", "?")
            path = result.get("file_path") or result.get("path") or ""
            lines.append(f"### Precedent {i} ({severity}/{domain})")
            if path:
                lines.append(f"File: `{path}`")
            lines.append(f"> {body}")
            lines.append("")

    lines.extend([
        "",
        f"Verify finding #{finding_index} and output your verdict as JSON.",
    ])

    return "\n".join(lines)


async def run_single_verification(
    finding: dict,
    index: int,
    diff_text: str,
    search_results: list,
    system_prompt: str,
    pr_number: int | None = None,
    repo: str = "micropython/micropython",
    cwd: str | None = None,
    env: dict | None = None,
) -> dict:
    """Spawn one claude -p subprocess to verify a single finding.

    Returns a verdict dict. On timeout/crash/bad JSON, returns an
    inconclusive verdict.
    """
    user_message = build_verification_user_message(
        finding, index, diff_text, search_results,
        pr_number=pr_number, repo=repo,
    )

    cmd = [
        "claude", "-p",
        "--model", VERIFICATION_MODEL,
        "--output-format", "json",
        "--json-schema", json.dumps(VERDICT_SCHEMA),
        "--dangerously-skip-permissions",
        "--system-prompt", system_prompt,
        "--allowedTools", "Bash,Read,Glob,Grep",
        "--max-budget-usd", MAX_BUDGET_USD,
    ]

    inconclusive = {
        "finding_index": index,
        "verdict": "inconclusive",
        "evidence": "",
        "adjusted_severity": None,
        "confidence": "low",
    }

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=cwd,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=user_message.encode()),
            timeout=VERIFICATION_TIMEOUT,
        )

        if proc.returncode != 0:
            logger.error(
                "Verification agent for finding #%d failed (rc=%d): %s",
                index, proc.returncode, stderr.decode(errors="replace")[:500],
            )
            inconclusive["evidence"] = f"Agent exited with code {proc.returncode}"
            return inconclusive

        # Parse structured output from claude -p --json-schema
        try:
            output = json.loads(stdout.decode())
        except json.JSONDecodeError:
            logger.error("Bad JSON from verification agent for finding #%d", index)
            inconclusive["evidence"] = "Agent returned invalid JSON"
            return inconclusive

        # Extract structured_output (same pattern as judge.py)
        if isinstance(output, dict) and "structured_output" in output:
            structured = output["structured_output"]
            if isinstance(structured, dict):
                structured["finding_index"] = index
                return structured

        if isinstance(output, dict) and "result" in output:
            result_val = output["result"]
            if isinstance(result_val, dict):
                result_val["finding_index"] = index
                return result_val
            if isinstance(result_val, str) and result_val.strip():
                parsed = json.loads(result_val)
                parsed["finding_index"] = index
                return parsed

        logger.error("No structured output from verification agent for finding #%d", index)
        inconclusive["evidence"] = "No structured output in agent response"
        return inconclusive

    except asyncio.TimeoutError:
        logger.error(
            "Verification agent for finding #%d timed out after %ds",
            index, VERIFICATION_TIMEOUT,
        )
        if proc is not None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except Exception as e:
                logger.debug("Subprocess cleanup after timeout: %s", e)
        inconclusive["evidence"] = f"Verification timed out after {VERIFICATION_TIMEOUT}s"
        return inconclusive

    except Exception as e:
        logger.error("Verification agent for finding #%d raised: %s", index, e)
        inconclusive["evidence"] = f"Agent error: {e}"
        return inconclusive


def write_verdict_file(temp_dir: str, finding: dict, verdict: dict) -> dict:
    """Write a verdict to a markdown file and return file info."""
    index = verdict.get("finding_index", 0)
    verdict_type = verdict.get("verdict", "inconclusive")
    safe_verdict = re.sub(r"[^a-z0-9_-]", "", verdict_type)
    filename = f"finding-{index}-{safe_verdict}.md"
    filepath = os.path.join(temp_dir, filename)

    original_severity = finding.get("severity", "unknown")
    adjusted = verdict.get("adjusted_severity")
    confidence = verdict.get("confidence", "low")
    evidence = verdict.get("evidence", "")

    lines = [
        f"# Finding #{index}: {verdict_type}",
        "",
        "## Original Finding",
        f"- **File:** `{finding.get('file', '?')}`",
        f"- **Line:** {finding.get('line', '?')}",
        f"- **Severity:** {original_severity}",
        f"- **Description:** {finding.get('description', '')}",
        "",
        "## Verdict",
        f"- **Verdict:** {verdict_type}",
        f"- **Confidence:** {confidence}",
        f"- **Adjusted Severity:** {adjusted or '(unchanged)'}",
        "",
        "## Evidence",
        evidence,
        "",
    ]

    content = "\n".join(lines)
    with open(filepath, "w") as f:
        f.write(content)

    return {
        "path": filepath,
        "finding_index": index,
        "original_severity": original_severity,
        "verdict": verdict_type,
        "adjusted_severity": adjusted,
        "confidence": confidence,
        "size_bytes": len(content.encode("utf-8")),
    }


def build_verification_orchestration_prompt(file_infos: list[dict]) -> str:
    """Build a compact orchestration prompt summarizing verification results."""
    if not file_infos:
        return "## Verification Results\n\nNo findings were verified."

    counts = {}
    for info in file_infos:
        v = info.get("verdict", "inconclusive")
        counts[v] = counts.get(v, 0) + 1

    lines = [
        "## Verification Results",
        "",
    ]

    summary_parts = []
    for verdict_type in ["confirmed", "partially_valid", "false_positive", "inconclusive"]:
        if verdict_type in counts:
            summary_parts.append(f"{counts[verdict_type]} {verdict_type}")
    lines.append(f"Summary: {', '.join(summary_parts)}")
    lines.append("")

    lines.append("| # | File | Original Severity | Verdict | Adjusted | Confidence |")
    lines.append("|---|------|-------------------|---------|----------|------------|")
    for info in file_infos:
        adjusted = info.get("adjusted_severity") or "\u2014"
        lines.append(
            f"| {info['finding_index']} "
            f"| `{info['path']}` "
            f"| {info['original_severity']} "
            f"| {info['verdict']} "
            f"| {adjusted} "
            f"| {info['confidence']} |"
        )

    lines.extend([
        "",
        "Read the verdict files above for evidence details. Apply verdicts:",
        "- **confirmed**: keep the finding as-is (or with adjusted severity)",
        "- **partially_valid**: keep but adjust severity/description per evidence",
        "- **false_positive**: drop the finding",
        "- **inconclusive**: use your judgment; the finding was not verified",
    ])

    return "\n".join(lines)


async def verify_all_findings(
    findings: list[dict],
    diff_text: str,
    pr_number: int | None = None,
    repo: str = "micropython/micropython",
    retriever=None,
    cwd: str | None = None,
    env: dict | None = None,
) -> tuple[str, list[dict]]:
    """Verify all findings in parallel using claude -p subprocesses.

    Args:
        findings: List of structured finding dicts.
        diff_text: Full unified diff text.
        pr_number: Optional PR number.
        repo: Repository slug.
        retriever: Warm retriever instance for pre-fetching review context.
        cwd: Working directory for subprocess (MicroPython checkout).
        env: Environment dict for subprocess.

    Returns:
        (orchestration_prompt, file_infos) tuple.
    """
    if not findings:
        return "## Verification Results\n\nNo findings to verify.", []

    if not shutil.which("claude"):
        return "Error: `claude` CLI not found on PATH. Cannot verify findings.", []

    # Pre-fetch review context for each finding
    search_results_map = {}
    if retriever is not None:
        for i, finding in enumerate(findings):
            query = f"{finding.get('file', '')} {finding.get('description', '')}"
            try:
                results = retriever.search_with_filters(query, top_k=5)
                search_results_map[i] = results
            except Exception as e:
                logger.warning("Pre-fetch for finding #%d failed: %s", i, e)
                search_results_map[i] = []
    else:
        for i in range(len(findings)):
            search_results_map[i] = []

    # Create temp directory for verdict files
    base = os.environ.get("MPY_REVIEW_TMPDIR")
    temp_dir = tempfile.mkdtemp(prefix="mpy-verify-", dir=base)

    system_prompt = build_verification_system_prompt()

    # Spawn all verification agents in parallel
    tasks = []
    for i, finding in enumerate(findings):
        tasks.append(
            run_single_verification(
                finding=finding,
                index=i,
                diff_text=diff_text,
                search_results=search_results_map.get(i, []),
                system_prompt=system_prompt,
                pr_number=pr_number,
                repo=repo,
                cwd=cwd,
                env=env,
            )
        )

    verdicts = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results and write verdict files
    file_infos = []
    for i, (finding, verdict) in enumerate(zip(findings, verdicts)):
        if isinstance(verdict, Exception):
            logger.error("Verification for finding #%d raised: %s", i, verdict)
            verdict = {
                "finding_index": i,
                "verdict": "inconclusive",
                "evidence": f"Agent error: {verdict}",
                "adjusted_severity": None,
                "confidence": "low",
            }
        file_info = write_verdict_file(temp_dir, finding, verdict)
        file_infos.append(file_info)

    prompt = build_verification_orchestration_prompt(file_infos)
    return prompt, file_infos
