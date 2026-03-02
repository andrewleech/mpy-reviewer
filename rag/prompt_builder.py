"""Prompt assembly for dpgeorge-style code review."""

from typing import List, Dict, Any, Optional
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ReviewContext:
    """Context assembled for code review."""

    diff_text: str
    review_examples: List[Dict[str, Any]]
    codebase_context: Optional[Dict[str, Any]] = None
    pr_number: Optional[int] = None
    pr_title: Optional[str] = None
    pr_body: Optional[str] = None
    files_changed: Optional[List[str]] = None
    commit_messages: Optional[List[str]] = field(default=None)


# Data-driven style guide extracted from 18,614 categorized review comments.
# Body length medians: blocking=121 chars, suggestion=126 chars, nitpick=45 chars.
# Top opening words: "I" (649), "This" (427), "Please" (157+105), "The" (118),
# "Is" (100), "If" (72), "Can" (69), "Why" (69), "Maybe" (60).
STYLE_GUIDE = """# dpgeorge Review Style (data-driven)

## Voice and Tone

dpgeorge's reviews are terse, technical, and direct. No pleasantries, no hedging,
no compliments on unrelated work. Feedback goes straight to the issue.

Common opening patterns (in order of frequency):
- Direct statement: "This should be...", "This needs...", "This will..."
- Question: "Is there a reason...?", "Why not...?", "Can this...?", "Does this...?"
- Instruction: "Please use...", "Please reorder...", "Please add..."
- Suggestion: "Maybe use...", "Would it be better to...?"
- Acknowledgment + pivot: "Ok, but...", "Yes, but..."

## Characteristic Brevity

Nitpicks are extremely short (median 45 characters). Examples from real reviews:
- "please no blank lines at start of files"
- "Remove blank line."
- "please put `void` in arg list"
- "please add in sorted order"
- "Can remove."
- "This debug line isn't needed."

Blocking comments are still concise (median 121 characters) but include enough
technical detail to explain why. They often include code corrections inline.

## What NOT to Do

- Do NOT open with "Great work on..." or "Thanks for..." — dpgeorge never does this.
- Do NOT use filler phrases like "I believe", "It seems like", "If I'm not mistaken".
- Do NOT explain obvious things. Assume the reader is an experienced developer.
- Do NOT wrap suggestions in excessive politeness. "Please use X" is sufficient.
- Do NOT use bullet-point lists where a single sentence suffices.

Bad (over-verbose, hedging):
> "I think it might be worth considering whether this could potentially be
> simplified by perhaps using a different approach. What do you think?"

Good (dpgeorge actual):
> "Why not `mp_obj_get_int(args[3])`? That will do error checking that it's an int."

Bad (gratuitous praise):
> "Nice work! This is looking really good. One small thing though..."

Good (dpgeorge actual):
> "This changes the error message. It now relies on `mp_unary_op` to raise
> the error which is more generic than the error from before."

## Severity Markers

- Blocking: stated as fact or requirement — "This needs...", "This is a bug", "should be X"
- Suggestion: often a question — "Is it worth...?", "Would it be better to...?"
- Nitpick: brief imperative — "please use X", "remove this", "add void"

## Technical Patterns

- References code with backticks: `mp_raise_ValueError`, `gc_collect()`
- Suggests concrete code fixes inline using fenced code blocks
- Points out subtle interactions ("this will break if...", "but now it won't work with...")
- Asks probing questions to understand design choices ("Why not...?", "Does this...?")
- Notes ordering/packing concerns ("Please reorder so the uint8_t's are together")

## Feedback Severity Levels

- **Blocking**: Must fix before merge (correctness bugs, missing error handling, ABI breaks)
- **Suggestion**: Should fix for quality (better patterns, cleaner API, documentation)
- **Nitpick**: Minor style/consistency (blank lines, naming, sorting)
"""

# Review methodology shared between the bot and MCP/plugin paths.
# Uses repo-relative paths — each consumer resolves actual filesystem paths.
REVIEW_GUIDANCE = """# Review Guidance

## Project Values

MicroPython values high code quality, small binary size, and runtime efficiency.
Evaluate every change against these priorities.

## Pre-Review Checks

Before analysing individual hunks, perform these checks:

1. **Coding conventions** — read `CODECONVENTIONS.md` at the repo root and verify
   the PR's code follows those conventions.
2. **PR description** — compare the PR description against
   `.github/pull_request_template.md`. The template expects Summary, Testing, and
   Trade-offs sections. Flag missing or empty sections.
3. **PR size** — if the PR spans multiple unrelated concerns, mixes refactoring
   with new features, or is so large that a human reviewer would struggle to
   evaluate it in one sitting, suggest breaking it into smaller, focused PRs.

## Using Provided Metadata

Commit messages, PR title, and PR description are provided separately from the
diff when available. Use this metadata to understand the author's intent. Do NOT
flag requirements (Signed-off-by, PR template fields, etc.) as missing if they
are satisfied in the provided metadata — diffs never contain commit trailers.

## Suggested Fixes

When the fix is obvious (renaming, typos, wrong operator, missing keyword, style
issues), include a GitHub suggestion block so the author can apply it with one
click:

````
```suggestion
corrected line(s) here
```
````

Only use suggestions for single-line or small multi-line fixes where you are
confident in the correction. For larger or ambiguous changes, describe the fix in
prose instead.
"""


class PromptBuilder:
    """Build prompts for dpgeorge-style code review."""

    def __init__(self, max_context_tokens: int = 15000):
        self.max_context_tokens = max_context_tokens

    def build_review_prompt(
        self,
        context: ReviewContext,
        include_style_guide: bool = True,
        include_examples: bool = True,
        include_codebase: bool = True,
        output_format: str = "markdown",
    ) -> str:
        """Build a complete review prompt.

        Section ordering: diff → codebase → examples → style guide + task.
        Style context is placed last so it is freshest in the model's
        attention when generation begins.
        """
        sections = []

        # 1. Code to review (first — establishes what we're reviewing)
        sections.append(self._format_code_to_review(context))

        # 2. Codebase context (if available)
        if include_codebase and context.codebase_context:
            sections.append(self._format_codebase_context(context.codebase_context))

        # 3. Review examples (concrete demonstrations)
        if include_examples and context.review_examples:
            sections.append(self._format_review_examples(context.review_examples))

        # 4. Style guide + task description (freshest in attention)
        if include_style_guide:
            sections.append(STYLE_GUIDE)
        sections.append(self._format_task_description())

        prompt = "\n\n".join(sections)

        if self._estimate_tokens(prompt) > self.max_context_tokens:
            logger.warning(
                f"Prompt exceeds token limit ({self._estimate_tokens(prompt)} > "
                f"{self.max_context_tokens}), truncating..."
            )
            prompt = self._truncate_prompt(prompt)

        return prompt

    def _format_review_examples(self, examples: List[Dict[str, Any]]) -> str:
        if not examples:
            return ""

        lines = ["# Relevant Past Reviews by dpgeorge\n"]

        for i, example in enumerate(examples, 1):
            lines.append(f"## Example {i}")
            lines.append(f"Domain: **{example.get('domain', 'N/A')}** | "
                        f"Severity: **{example.get('severity', 'N/A')}**")

            score = example.get("rrf_score") or example.get("rerank_score")
            if score:
                lines.append(f"Relevance: {score:.2%}")

            file_path = example.get("file_path") or example.get("path")
            if file_path:
                lines.append(f"File: `{file_path}`")

            if example.get("diff_hunk"):
                lines.append("\nCode context:")
                lines.append("```diff")
                diff = example["diff_hunk"]
                if len(diff) > 500:
                    diff = diff[:500] + "\n... (truncated)"
                lines.append(diff)
                lines.append("```")

            lines.append("\ndpgeorge's feedback:")
            lines.append(f"> {example['body']}")

            # Thread context if available (from graph expansion)
            if example.get("thread"):
                lines.append("\nRelated comments in thread:")
                for msg in example["thread"]:
                    body = msg.get("body", "")[:300]
                    lines.append(f"> {body}")

            metadata = []
            if example.get("is_style_example"):
                metadata.append("_style example_")
            if example.get("is_pattern"):
                metadata.append("_reusable pattern_")
            if example.get("has_code_suggestion"):
                metadata.append("_includes code suggestion_")

            if metadata:
                lines.append(f"\n_{', '.join(metadata)}_")

            lines.append("\n---\n")

        return "\n".join(lines)

    def _format_codebase_context(self, context: Dict[str, Any]) -> str:
        lines = ["# MicroPython Codebase Context\n"]

        if context.get("related_definitions"):
            lines.append("## Relevant Definitions\n")
            for defn in context["related_definitions"][:3]:
                lines.append(f"### {defn.get('symbol', 'Symbol')} ({defn.get('type', 'unknown')})")
                lines.append(f"File: `{defn.get('file', 'N/A')}` "
                            f"(line {defn.get('line', '?')})")
                lines.append("```c")
                lines.append(defn.get("context", ""))
                lines.append("```\n")

        if context.get("similar_patterns"):
            lines.append("## Similar Code Patterns\n")
            for pattern in context["similar_patterns"][:3]:
                lines.append(f"- `{pattern.get('file', 'N/A')}` "
                            f"({pattern.get('match_count', 0)} keyword matches)")

        return "\n".join(lines)

    def _format_code_to_review(self, context: ReviewContext) -> str:
        lines = ["# Code to Review\n"]

        if context.pr_number:
            lines.append(f"## PR #{context.pr_number}")
            if context.pr_title:
                lines.append(f"Title: {context.pr_title}")
            if context.pr_body:
                body = context.pr_body
                if len(body) > 2000:
                    body = body[:2000] + "\n... (truncated)"
                lines.append(f"\nDescription:\n{body}")
            if context.files_changed:
                lines.append(f"Files changed: {', '.join(context.files_changed)}")
            if context.commit_messages:
                lines.append("\nCommit messages:")
                for msg in context.commit_messages:
                    lines.append(f"- {msg}")
            lines.append("")

        lines.append("## Diff\n")
        lines.append("```diff")
        lines.append(context.diff_text)
        lines.append("```")

        return "\n".join(lines)

    def _format_task_description(self) -> str:
        return REVIEW_GUIDANCE + """
# Your Task

Review the code above in dpgeorge's style. Be direct, technical, and concise.

Before analysing individual hunks:
- Locate and read `CODECONVENTIONS.md` at the MicroPython repo root
- Locate and read `.github/pull_request_template.md` to check the PR description

For each issue found, provide:
1. The file and line/hunk reference
2. Severity: **Blocking** / **Suggestion** / **Nitpick**
3. The feedback itself — terse for nitpicks, detailed for blocking issues

Prioritize:
- Correctness: logic bugs, edge cases, error handling
- Memory: embedded constraints, allocation, leaks
- API design: clean interfaces, backwards compatibility
- Code style: MicroPython conventions
- Portability: cross-platform assumptions

Match the tone and brevity of the examples above. Do not pad feedback with
filler or compliments."""

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def _truncate_prompt(self, prompt: str) -> str:
        """Truncate prompt to fit within token limit.

        Keeps: code to review (first) and style guide + task (last).
        Trims: codebase context and examples from the middle.
        """
        sections = prompt.split("\n\n# ")
        if len(sections) <= 2:
            return prompt

        first = sections[0]
        last = sections[-1]
        middle = sections[1:-1]

        # Reserve space for the bookend sections
        bookend_tokens = self._estimate_tokens(
            "\n\n# ".join([first, last])
        )
        remaining_budget = self.max_context_tokens - bookend_tokens

        # Greedily add middle sections within budget
        kept_middle = []
        for section in middle:
            section_tokens = self._estimate_tokens("\n\n# " + section)
            if remaining_budget >= section_tokens:
                kept_middle.append(section)
                remaining_budget -= section_tokens

        return "\n\n# ".join([first] + kept_middle + [last])

    # --- File-based orchestration for MCP ---

    def write_example_files(
        self,
        examples: List[Dict[str, Any]],
        temp_dir: Optional[str] = None,
    ) -> tuple:
        """Write each review example to its own markdown file.

        Args:
            examples: Retrieved review examples.
            temp_dir: Directory to write files to. Created if None.

        Returns:
            (temp_dir, file_infos) where file_infos is a list of dicts
            with keys: path, index, severity, domain, theme, size_bytes.
        """
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="mpy-review-")

        file_infos = []
        for i, example in enumerate(examples, 1):
            severity = example.get("severity", "unknown")
            domain = example.get("domain", "unknown")
            # Sanitize for filename
            safe_sev = re.sub(r"[^a-z0-9_-]", "", severity)
            safe_dom = re.sub(r"[^a-z0-9_-]", "", domain)
            filename = f"ex-{i}-{safe_sev}-{safe_dom}.md"
            filepath = os.path.join(temp_dir, filename)

            content = self._format_example_file(i, example)
            with open(filepath, "w") as f:
                f.write(content)

            file_infos.append({
                "path": filepath,
                "index": i,
                "severity": severity,
                "domain": domain,
                "theme": example.get("theme", ""),
                "size_bytes": len(content.encode("utf-8")),
            })

        return temp_dir, file_infos

    def _format_example_file(self, index: int, example: Dict[str, Any]) -> str:
        """Format a single review example as a standalone markdown file."""
        severity = example.get("severity", "N/A")
        domain = example.get("domain", "N/A")
        file_path = example.get("file_path") or example.get("path") or ""
        pr_number = example.get("pr_number", "")
        comment_id = example.get("comment_id", "")

        lines = [
            f"# Review Example {index}: {severity} / {domain}",
            f"- PR: #{pr_number}" if pr_number else "",
            f"- File: `{file_path}`" if file_path else "",
            f"- Comment ID: {comment_id}" if comment_id else "",
        ]
        lines = [l for l in lines if l]  # drop empty

        score = example.get("rrf_score") or example.get("rerank_score")
        if score:
            lines.append(f"- Relevance: {score:.2%}")

        tags = []
        if example.get("is_style_example"):
            tags.append("style example")
        if example.get("is_pattern"):
            tags.append("reusable pattern")
        if example.get("has_code_suggestion"):
            tags.append("includes code suggestion")
        if tags:
            lines.append(f"- Tags: {', '.join(tags)}")

        lines.append("")
        lines.append("## Reviewer Feedback")
        lines.append(example.get("body", ""))

        if example.get("diff_hunk"):
            lines.append("")
            lines.append("## Original Code Context")
            lines.append("```diff")
            lines.append(example["diff_hunk"])
            lines.append("```")

        if example.get("thread"):
            lines.append("")
            lines.append("## Thread Context")
            for msg in example["thread"]:
                body = msg.get("body", "")
                lines.append(f"> {body}")
                lines.append("")

        lines.append("")
        return "\n".join(lines)

    def build_orchestration_prompt(
        self,
        file_infos: List[Dict[str, Any]],
        files_changed: Optional[List[str]] = None,
        pr_number: Optional[int] = None,
        pr_title: Optional[str] = None,
        pr_body: Optional[str] = None,
        commit_messages: Optional[List[str]] = None,
        codebase_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build a compact orchestration prompt with file paths and style guide.

        This replaces the monolithic prompt for MCP usage. The calling agent
        already has the diff in its context, so we don't echo it back.

        Args:
            file_infos: List of dicts from write_example_files.
            files_changed: File paths from the diff (for reference).
            pr_number: PR number if reviewing a PR.
            pr_title: PR title.
            pr_body: PR description/body.
            commit_messages: List of commit messages.
            codebase_context: Optional codebase context dict.
        """
        sections = []

        sections.append("# MicroPython Review Context")

        if pr_number:
            sections.append(f"\nReviewing PR #{pr_number}")
        if pr_title:
            sections.append(f"Title: {pr_title}")
        if pr_body:
            body = pr_body
            if len(body) > 2000:
                body = body[:2000] + "\n... (truncated)"
            sections.append(f"\nDescription:\n{body}")
        if files_changed:
            sections.append(f"\nFiles in diff: {', '.join(files_changed)}")
        if commit_messages:
            sections.append("\nCommit messages:")
            for msg in commit_messages:
                sections.append(f"- {msg}")

        # Example summary table
        sections.append("")
        sections.append("## Retrieved Examples")
        sections.append("")
        sections.append("| # | File | Size | Severity | Domain | Summary |")
        sections.append("|---|------|------|----------|--------|---------|")
        for info in file_infos:
            size = _format_size(info["size_bytes"])
            theme = info.get("theme", "")
            if len(theme) > 50:
                theme = theme[:47] + "..."
            sections.append(
                f"| {info['index']} | `{info['path']}` | {size} "
                f"| {info['severity']} | {info['domain']} | {theme} |"
            )

        # Codebase context (inline, usually small)
        if codebase_context:
            sections.append("")
            sections.append(self._format_codebase_context(codebase_context))

        # Review guidance + style guide (always included)
        sections.append("")
        sections.append(REVIEW_GUIDANCE)
        sections.append("")
        sections.append(STYLE_GUIDE)

        # Workflow instructions
        sections.append("")
        sections.append(self._format_orchestration_task())

        return "\n".join(sections)

    def _format_orchestration_task(self) -> str:
        return """## Suggested Workflow

You already have the project diff in context. The files above contain
past review examples with their original code context (diff hunks).

- For small files (<2KB): read directly with the Read tool
- For large files (>2KB): consider spawning agents to evaluate the
  project diff against each reference file in parallel
- Locate and read `CODECONVENTIONS.md` at the MicroPython repo root
- Locate and read `.github/pull_request_template.md` to check the PR description
- Assemble individual findings into a final review

## Your Task

Review the code diff in dpgeorge's style. Be direct, technical, and concise.

For each issue found, provide:
1. The file and line/hunk reference
2. Severity: **Blocking** / **Suggestion** / **Nitpick**
3. The feedback itself — terse for nitpicks, detailed for blocking issues

Prioritize:
- Correctness: logic bugs, edge cases, error handling
- Memory: embedded constraints, allocation, leaks
- API design: clean interfaces, backwards compatibility
- Code style: MicroPython conventions
- Portability: cross-platform assumptions

Match the tone and brevity of the examples. Do not pad feedback with
filler or compliments."""


def _format_size(size_bytes: int) -> str:
    """Format byte count as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    return f"{size_bytes / 1024:.1f} KB"


# Global prompt builder instance
_builder: Optional[PromptBuilder] = None


def get_builder(max_tokens: int = 15000) -> PromptBuilder:
    global _builder
    if _builder is None:
        _builder = PromptBuilder(max_context_tokens=max_tokens)
    return _builder


def build_prompt(
    diff_text: str,
    review_examples: List[Dict[str, Any]],
    codebase_context: Optional[Dict[str, Any]] = None,
    pr_number: Optional[int] = None,
    pr_title: Optional[str] = None,
) -> str:
    """Convenience function to build a review prompt."""
    context = ReviewContext(
        diff_text=diff_text,
        review_examples=review_examples,
        codebase_context=codebase_context,
        pr_number=pr_number,
        pr_title=pr_title,
    )

    builder = get_builder()
    return builder.build_review_prompt(context)
