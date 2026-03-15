"""Prompt assembly for MicroPython issue triage."""

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


TRIAGE_STYLE_GUIDE = """# MicroPython Issue Triage Style (data-driven)

## Voice and Tone

Triage responses are terse, technical, and direct. No pleasantries,
no hedging, no compliments on unrelated work.

Common patterns on issues:
- Ask for specifics: "Which port?", "What firmware version?", "Can you provide a minimal script?"
- Point to code: "See `py/runtime.c` line 123", "The relevant code is in `extmod/modbluetooth.c`"
- State duplicates directly: "Duplicate of #1234", "This was fixed by PR #5678"
- Reference design decisions: "This is by design — see discussion in #9012"
- Close with evidence: "Fixed by PR #X (merged YYYY-MM-DD). Closing."

## What NOT to Do

- Do NOT open with "Thank you for reporting..."
- Do NOT hedge with "I believe" or "It seems like"
- Do NOT over-explain. Assume the reader understands MicroPython basics.
- Do NOT use bullet-point lists where a single sentence suffices.

## When to Ask for More Info

- Missing port/board info
- No firmware version
- No minimal reproducer script
- Vague description without concrete steps
"""


@dataclass
class TriageContext:
    """Context assembled for issue triage."""

    issue_number: int
    issue_title: str
    issue_body: str
    issue_labels: List[str]
    issue_state: str
    issue_repo: str = "micropython/micropython"
    similar_issues: Optional[List[Dict[str, Any]]] = None
    related_reviews: Optional[List[Dict[str, Any]]] = None
    closing_refs: Optional[List[Dict[str, Any]]] = None
    codebase_context: Optional[Dict[str, Any]] = None


class TriagePromptBuilder:
    """Build prompts for MicroPython issue triage."""

    def build_triage_prompt(self, context: TriageContext) -> str:
        """Build a complete triage prompt.

        Section ordering: issue text → similar issues → closing refs →
        related reviews → codebase context → style guide → task.
        """
        sections = []

        # 1. The issue being triaged
        sections.append(self._format_issue(context))

        # 2. Closing references (high-confidence signal)
        if context.closing_refs:
            sections.append(self._format_closing_refs(context.closing_refs))

        # 3. Similar issues found
        if context.similar_issues:
            sections.append(self._format_similar_issues(context.similar_issues))

        # 4. Related review comments
        if context.related_reviews:
            sections.append(self._format_related_reviews(context.related_reviews))

        # 5. Codebase context
        if context.codebase_context:
            sections.append(self._format_codebase_context(context.codebase_context))

        # 6. Style guide + task (freshest in attention)
        sections.append(TRIAGE_STYLE_GUIDE)
        sections.append(self._format_triage_task(context))

        return "\n\n".join(sections)

    def _format_issue(self, context: TriageContext) -> str:
        lines = [f"# Issue #{context.issue_number}: {context.issue_title}"]
        lines.append(f"- Repo: {context.issue_repo}")
        lines.append(f"- State: {context.issue_state}")
        if context.issue_labels:
            lines.append(f"- Labels: {', '.join(context.issue_labels)}")
        else:
            lines.append("- Labels: (none)")
        lines.append("")
        lines.append("## Issue Body")
        lines.append(context.issue_body or "(empty)")
        return "\n".join(lines)

    def _format_closing_refs(self, refs: List[Dict[str, Any]]) -> str:
        lines = ["# Closing References"]
        lines.append("")
        for ref in refs:
            merged = "merged" if ref.get("pr_merged") else "not merged"
            lines.append(
                f"- PR #{ref['pr_number']} ({ref['pr_repo']}) — {merged}"
            )
        return "\n".join(lines)

    def _format_similar_issues(self, issues: List[Dict[str, Any]]) -> str:
        lines = ["# Similar Issues Found"]
        lines.append("")
        for i, issue in enumerate(issues, 1):
            state = issue.get("state", "?")
            title = issue.get("title", "?")
            number = issue.get("issue_number", "?")
            repo = issue.get("repo", "")
            score = issue.get("rrf_score", 0)
            labels = issue.get("labels", "")
            if isinstance(labels, str):
                try:
                    labels = json.loads(labels)
                except (json.JSONDecodeError, TypeError):
                    labels = []
            label_str = ", ".join(labels) if labels else "none"
            lines.append(f"## {i}. #{number} ({state}) — {title}")
            lines.append(f"   Labels: {label_str} | Score: {score:.4f}")
            body = issue.get("body", "") or ""
            if len(body) > 300:
                body = body[:300] + "..."
            if body:
                lines.append(f"   > {body}")
            lines.append("")
        return "\n".join(lines)

    def _format_related_reviews(self, reviews: List[Dict[str, Any]]) -> str:
        lines = ["# Related Review Comments"]
        lines.append("")
        for i, review in enumerate(reviews, 1):
            domain = review.get("domain", "?")
            severity = review.get("severity", "?")
            pr = review.get("pr_number", "?")
            body = review.get("body", "")
            if len(body) > 300:
                body = body[:300] + "..."
            lines.append(f"## {i}. PR #{pr} — {domain}/{severity}")
            lines.append(f"> {body}")
            lines.append("")
        return "\n".join(lines)

    def _format_codebase_context(self, context: Dict[str, Any]) -> str:
        lines = ["# MicroPython Codebase Context"]
        lines.append("")
        if context.get("related_definitions"):
            lines.append("## Relevant Definitions")
            for defn in context["related_definitions"][:3]:
                lines.append(f"- `{defn.get('symbol', '?')}` in `{defn.get('file', '?')}`"
                            f" (line {defn.get('line', '?')})")
        if context.get("similar_patterns"):
            lines.append("## Similar Code Patterns")
            for pattern in context["similar_patterns"][:3]:
                lines.append(f"- `{pattern.get('file', '?')}` "
                            f"({pattern.get('match_count', 0)} keyword matches)")
        return "\n".join(lines)

    def _format_triage_task(self, context: TriageContext) -> str:
        from triage.labels import VALID_LABELS
        label_list = ", ".join(sorted(VALID_LABELS))

        return f"""# Your Task

Triage issue #{context.issue_number}. Be direct, technical, and concise.

## 1. Classification

Assign labels from: {label_list}

Consider:
- Component: which part of MicroPython does this affect?
- Port: is this port-specific? Which port?
- Type: bug, enhancement, or rfc?

## 2. Duplicate / Resolution Check

Based on similar issues and closing references above:
- Is this a duplicate of another issue?
- Was this already fixed by a merged PR?
- If resolved, state the evidence.

## 3. Response Draft

Draft a triage response:
- If resolved: state the fix with PR link
- If duplicate: reference the original issue
- If needs info: ask the specific missing information
- If classifiable: note the component/port

## Output Format

Provide your assessment as:
1. **Labels**: list of labels to apply (with confidence: high/medium/low)
2. **Duplicate/Resolved**: verdict with evidence (or "none found")
3. **Response**: draft comment text
"""

    def write_triage_example_files(
        self,
        similar_issues: List[Dict[str, Any]],
        temp_dir: Optional[str] = None,
    ) -> tuple:
        """Write each similar issue to its own file (parallel to rag/prompt_builder.py).

        Returns:
            (temp_dir, file_infos) where file_infos has path, index, size_bytes.
        """
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="mpy-triage-")

        file_infos = []
        for i, issue in enumerate(similar_issues, 1):
            state = issue.get("state", "unknown")
            safe_state = re.sub(r"[^a-z0-9_-]", "", state)
            filename = f"issue-{i}-{safe_state}.md"
            filepath = os.path.join(temp_dir, filename)

            content = self._format_issue_file(i, issue)
            with open(filepath, "w") as f:
                f.write(content)

            file_infos.append({
                "path": filepath,
                "index": i,
                "state": state,
                "issue_number": issue.get("issue_number"),
                "size_bytes": len(content.encode("utf-8")),
            })

        return temp_dir, file_infos

    def _format_issue_file(self, index: int, issue: Dict[str, Any]) -> str:
        number = issue.get("issue_number", "?")
        title = issue.get("title", "?")
        state = issue.get("state", "?")
        repo = issue.get("repo", "")
        labels = issue.get("labels", "")
        if isinstance(labels, str):
            try:
                labels = json.loads(labels)
            except (json.JSONDecodeError, TypeError):
                labels = []

        lines = [
            f"# Similar Issue #{number}: {title}",
            f"- State: {state}",
            f"- Repo: {repo}",
            f"- Labels: {', '.join(labels) if labels else 'none'}",
        ]

        score = issue.get("rrf_score")
        if score:
            lines.append(f"- Relevance: {score:.4f}")

        lines.append("")
        lines.append("## Body")
        lines.append(issue.get("body", "") or "(empty)")
        lines.append("")
        return "\n".join(lines)


# Global instance
_triage_builder: Optional[TriagePromptBuilder] = None


def get_triage_builder() -> TriagePromptBuilder:
    global _triage_builder
    if _triage_builder is None:
        _triage_builder = TriagePromptBuilder()
    return _triage_builder
