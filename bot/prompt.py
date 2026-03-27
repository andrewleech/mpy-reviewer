"""Diff annotation and user message assembly for bot-driven reviews.

Provides line-number annotation for unified diffs and security-hardened
user message construction. System prompt assembly has moved to the
multi-agent review pipeline (mpy-rules/prompts/).
"""

import re

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def annotate_diff(diff: str) -> str:
    """Prefix each diff line with old-file (L) and new-file (R) line numbers.

    Hunk headers, file headers, and '\\ No newline' lines pass through unchanged.
    Context lines get both L and R numbers; removed lines get L only; added lines
    get R only. Each column is 5 chars wide for alignment up to 99999.
    """
    if not diff:
        return diff

    out: list[str] = []
    left = right = 0

    for line in diff.split("\n"):
        if line.startswith("diff --git") or line.startswith("---") or line.startswith("+++"):
            out.append(line)
            continue

        m = _HUNK_RE.match(line)
        if m:
            left = int(m.group(1))
            right = int(m.group(2))
            out.append(line)
            continue

        if line.startswith("\\ "):
            out.append(line)
            continue

        if line.startswith("-"):
            out.append(f"L{left:<5}     {line}")
            left += 1
        elif line.startswith("+"):
            out.append(f"      R{right:<4}{line}")
            right += 1
        elif left or right:
            # Context line (starts with ' ' or is empty inside a hunk)
            out.append(f"L{left:<5}R{right:<4}{line}")
            left += 1
            right += 1
        else:
            out.append(line)

    return "\n".join(out)


def _sanitize_untrusted(text: str) -> str:
    """Strip fake delimiter tags from untrusted PR content.

    Stripping (vs. escaping) is intentional: these exact strings should never
    appear in legitimate code diffs. Removing them preserves readability while
    preventing delimiter injection. The system prompt's first/last tag rule
    provides a second layer of defense.
    """
    return text.replace("<untrusted-pr-content>", "").replace("</untrusted-pr-content>", "")


def build_user_message(
    diff_text: str,
    pr_number: int,
    pr_title: str,
    pr_body: str,
    repo_owner: str,
    repo_name: str,
    head_sha: str = "",
) -> str:
    """Build the user message containing the PR content for review.

    Wraps untrusted content in security delimiters.

    Args:
        diff_text: Unified diff of the PR.
        pr_number: PR number.
        pr_title: PR title.
        pr_body: PR description body.
        repo_owner: Repository owner.
        repo_name: Repository name.
        head_sha: Head commit SHA (for pinning the review).
    """
    lines = [
        f"Review PR #{pr_number} on {repo_owner}/{repo_name}.",
    ]
    if head_sha:
        lines.append(f"Head commit: {head_sha}")
    lines.append("")
    lines.append("<untrusted-pr-content>")
    lines.append(f"Title: {_sanitize_untrusted(pr_title)}")
    lines.append("")
    if pr_body:
        lines.append(f"Description:\n{_sanitize_untrusted(pr_body)}")
        lines.append("")
    lines.append("Diff:")
    lines.append("```diff")
    lines.append(annotate_diff(_sanitize_untrusted(diff_text)))
    lines.append("```")
    lines.append("</untrusted-pr-content>")

    return "\n".join(lines)
