"""Prompt assembly for dpgeorge-style code review."""

from typing import List, Dict, Any, Optional
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ReviewContext:
    """Context assembled for code review."""

    diff_text: str
    review_examples: List[Dict[str, Any]]
    codebase_context: Optional[Dict[str, Any]] = None
    pr_number: Optional[int] = None
    pr_title: Optional[str] = None
    files_changed: Optional[List[str]] = None
    commit_message: Optional[str] = None


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
            if context.files_changed:
                lines.append(f"Files changed: {', '.join(context.files_changed)}")
            if context.commit_message:
                lines.append(f"\nCommit message:\n> {context.commit_message}")
            lines.append("")

        lines.append("## Diff\n")
        lines.append("```diff")
        diff = context.diff_text
        if len(diff) > 5000:
            lines.append(diff[:5000])
            lines.append("\n... (diff truncated for length)")
        else:
            lines.append(diff)
        lines.append("```")

        return "\n".join(lines)

    def _format_task_description(self) -> str:
        return """# Your Task

Review the code above in dpgeorge's style. Be direct, technical, and concise.

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
