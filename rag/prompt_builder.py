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


class PromptBuilder:
    """Build comprehensive prompts for dpgeorge-style code review."""

    # Style guide excerpt (static)
    STYLE_GUIDE = """# dpgeorge Review Principles

dpgeorge's code reviews focus on:

1. **Correctness**: Logic bugs, edge cases, error handling
   - Check for off-by-one errors, uninitialized variables
   - Ensure error conditions are properly handled
   - Validate assumptions about input data

2. **Code Style & Conventions**:
   - MicroPython coding standards (C for core, Python style elsewhere)
   - Consistent naming: snake_case for functions, UPPER_CASE for constants
   - Proper indentation and brace placement
   - Clear, self-documenting code

3. **Memory Efficiency**:
   - Embedded systems constraints - minimize allocations
   - Stack vs heap usage appropriate for platform
   - No memory leaks or dangling pointers
   - Efficient data structures for constrained environments

4. **API Design**:
   - Clean, intuitive interfaces
   - Backwards compatibility when modifying public APIs
   - Proper documentation for exported functions
   - Avoid unnecessary complexity

5. **Performance**:
   - Avoid unnecessary operations in tight loops
   - Consider both time and space complexity
   - Profile-driven optimization (avoid premature optimization)

6. **Portability**:
   - Code works across MicroPython's supported platforms
   - Platform-specific code is properly isolated
   - No assumptions about architecture (endianness, pointer size)

## Feedback Severity

- **Blocking**: Must fix before merge (correctness issues, critical bugs)
- **Suggestion**: Should fix for quality (improvements, better patterns)
- **Nitpick**: Minor style or consistency (not critical, reviewable together)

dpgeorge is respectful but direct. Feedback is technical and actionable.
"""

    def __init__(self, max_context_tokens: int = 15000):
        """Initialize the prompt builder.

        Args:
            max_context_tokens: Maximum tokens for context
        """
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

        Args:
            context: ReviewContext with diff and retrieved examples
            include_style_guide: Include the style guide section
            include_examples: Include past review examples
            include_codebase: Include codebase context
            output_format: Output format ("markdown" or "text")

        Returns:
            Complete prompt for the reviewer model
        """
        sections = []

        # Style guide
        if include_style_guide:
            sections.append(self.STYLE_GUIDE)

        # Review examples
        if include_examples and context.review_examples:
            sections.append(self._format_review_examples(context.review_examples))

        # Codebase context
        if include_codebase and context.codebase_context:
            sections.append(self._format_codebase_context(context.codebase_context))

        # Code to review
        sections.append(self._format_code_to_review(context))

        # Task description
        sections.append(self._format_task_description())

        prompt = "\n\n".join(sections)

        # Truncate if needed
        if self._estimate_tokens(prompt) > self.max_context_tokens:
            logger.warning(
                f"Prompt exceeds token limit ({self._estimate_tokens(prompt)} > "
                f"{self.max_context_tokens}), truncating..."
            )
            prompt = self._truncate_prompt(prompt)

        return prompt

    def _format_review_examples(self, examples: List[Dict[str, Any]]) -> str:
        """Format past review examples.

        Args:
            examples: List of review examples

        Returns:
            Formatted section
        """
        if not examples:
            return ""

        lines = ["# Relevant Past Reviews by dpgeorge\n"]

        for i, example in enumerate(examples, 1):
            lines.append(f"## Example {i}")
            lines.append(f"Domain: **{example.get('domain', 'N/A')}** | "
                        f"Severity: **{example.get('severity', 'N/A')}**")

            # Add relevance score if available
            score = example.get("rrf_score") or example.get("rerank_score")
            if score:
                lines.append(f"Relevance: {score:.2%}")

            # Add file context if available
            if example.get("path"):
                lines.append(f"File: `{example['path']}`")

            # Add code context
            if example.get("diff_hunk"):
                lines.append("\nCode context:")
                lines.append("```diff")
                diff = example["diff_hunk"]
                # Limit diff length
                if len(diff) > 500:
                    diff = diff[:500] + "\n... (truncated)"
                lines.append(diff)
                lines.append("```")

            # Add the comment
            lines.append("\ndpgeorge's feedback:")
            lines.append(f"> {example['body']}")

            # Add metadata if available
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
        """Format codebase context.

        Args:
            context: Codebase context dictionary

        Returns:
            Formatted section
        """
        lines = ["# MicroPython Codebase Context\n"]

        # Related definitions
        if context.get("related_definitions"):
            lines.append("## Relevant Definitions\n")
            for defn in context["related_definitions"][:3]:  # Top 3
                lines.append(f"### {defn.get('symbol', 'Symbol')} ({defn.get('type', 'unknown')})")
                lines.append(f"File: `{defn.get('file', 'N/A')}` "
                            f"(line {defn.get('line', '?')})")
                lines.append("```c")
                lines.append(defn.get("context", ""))
                lines.append("```\n")

        # Similar patterns
        if context.get("similar_patterns"):
            lines.append("## Similar Code Patterns\n")
            for pattern in context["similar_patterns"][:3]:  # Top 3
                lines.append(f"- `{pattern.get('file', 'N/A')}` "
                            f"({pattern.get('match_count', 0)} keyword matches)")

        return "\n".join(lines)

    def _format_code_to_review(self, context: ReviewContext) -> str:
        """Format the code being reviewed.

        Args:
            context: ReviewContext

        Returns:
            Formatted section
        """
        lines = ["# Code to Review\n"]

        # PR info if available
        if context.pr_number:
            lines.append(f"## PR #{context.pr_number}")
            if context.pr_title:
                lines.append(f"Title: {context.pr_title}")
            if context.files_changed:
                lines.append(f"Files changed: {', '.join(context.files_changed)}")
            if context.commit_message:
                lines.append(f"\nCommit message:\n> {context.commit_message}")
            lines.append("")

        # The diff
        lines.append("## Diff\n")
        lines.append("```diff")
        diff = context.diff_text
        # Limit total diff size but keep it readable
        if len(diff) > 5000:
            lines.append(diff[:5000])
            lines.append("\n... (diff truncated for length)")
        else:
            lines.append(diff)
        lines.append("```")

        return "\n".join(lines)

    def _format_task_description(self) -> str:
        """Format the task description.

        Returns:
            Task description section
        """
        return """# Your Task

You are a code reviewer with dpgeorge's expertise and attention to detail. Review the code above
in their style, considering:

1. **Correctness**: Are there any logic bugs, edge cases, or error handling issues?
2. **Code Style**: Does the code follow MicroPython conventions?
3. **Memory Efficiency**: Is the code appropriate for embedded systems?
4. **API Design**: Is the interface clean and well-designed?
5. **Portability**: Will the code work across MicroPython's platforms?

Provide specific, actionable feedback with appropriate severity:
- **Blocking**: Must fix before merge
- **Suggestion**: Should fix for quality
- **Nitpick**: Minor style issues

Be direct and technical, like dpgeorge. Reference the provided examples where relevant."""

    def _estimate_tokens(self, text: str) -> int:
        """Rough estimate of token count (approximate).

        Uses ~1 token per 4 characters as a heuristic.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        return len(text) // 4

    def _truncate_prompt(self, prompt: str) -> str:
        """Truncate prompt to fit within token limit.

        Prioritizes: style guide > examples > codebase > diff

        Args:
            prompt: Full prompt

        Returns:
            Truncated prompt
        """
        # Simple strategy: remove examples until it fits
        sections = prompt.split("\n\n# ")
        style_guide = sections[0]

        # Keep style guide and task
        result = [style_guide]

        for section in sections[1:]:
            test_prompt = "\n\n# ".join(result + [section])
            if self._estimate_tokens(test_prompt) <= self.max_context_tokens:
                result.append(section)

        return "\n\n# ".join(result)


# Global prompt builder instance
_builder: Optional[PromptBuilder] = None


def get_builder(max_tokens: int = 15000) -> PromptBuilder:
    """Get or create a prompt builder.

    Args:
        max_tokens: Maximum context tokens

    Returns:
        PromptBuilder instance
    """
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
    """Convenience function to build a review prompt.

    Args:
        diff_text: Code diff
        review_examples: Past review examples
        codebase_context: Codebase context
        pr_number: PR number if available
        pr_title: PR title if available

    Returns:
        Complete review prompt
    """
    context = ReviewContext(
        diff_text=diff_text,
        review_examples=review_examples,
        codebase_context=codebase_context,
        pr_number=pr_number,
        pr_title=pr_title,
    )

    builder = get_builder()
    return builder.build_review_prompt(context)
