"""Variant definitions and prompt construction for the benchmark."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Variant:
    """A benchmark variant configuration."""

    id: str
    model_name: str
    uses_rag: bool
    backend: str  # "ollama" or "claude"
    description: str
    claude_model: Optional[str] = None  # "sonnet" or "opus" for claude backend

    @property
    def prompt_type(self) -> str:
        return "rag" if self.uses_rag else "bare"


VARIANTS = {
    "ft_f16": Variant(
        id="ft_f16",
        model_name="micropython-expert:f16",
        uses_rag=False,
        backend="ollama",
        description="Fine-tuned Qwen2.5-Coder-7B (F16, no RAG)",
    ),
    "ft_q4": Variant(
        id="ft_q4",
        model_name="micropython-expert:q4-k-m",
        uses_rag=False,
        backend="ollama",
        description="Fine-tuned Qwen2.5-Coder-7B (Q4_K_M, no RAG)",
    ),
    "ft_f16_rag": Variant(
        id="ft_f16_rag",
        model_name="micropython-expert:f16",
        uses_rag=True,
        backend="ollama",
        description="Fine-tuned Qwen2.5-Coder-7B (F16, with RAG)",
    ),
    "sonnet_bare": Variant(
        id="sonnet_bare",
        model_name="claude-sonnet-4-5-20250929",
        uses_rag=False,
        backend="claude",
        claude_model="sonnet",
        description="Claude Sonnet 4.5 (no RAG)",
    ),
    "opus_bare": Variant(
        id="opus_bare",
        model_name="claude-opus-4-6",
        uses_rag=False,
        backend="claude",
        claude_model="opus",
        description="Claude Opus 4.6 (no RAG)",
    ),
    "sonnet_rag": Variant(
        id="sonnet_rag",
        model_name="claude-sonnet-4-5-20250929",
        uses_rag=True,
        backend="claude",
        claude_model="sonnet",
        description="Claude Sonnet 4.5 (with RAG)",
    ),
    "opus_rag": Variant(
        id="opus_rag",
        model_name="claude-opus-4-6",
        uses_rag=True,
        backend="claude",
        claude_model="opus",
        description="Claude Opus 4.6 (with RAG)",
    ),
    "base_qwen": Variant(
        id="base_qwen",
        model_name="qwen2.5-coder:7b-instruct",
        uses_rag=False,
        backend="ollama",
        description="Base Qwen2.5-Coder-7B-Instruct (Q4, no RAG)",
    ),
    "base_qwen_rag": Variant(
        id="base_qwen_rag",
        model_name="qwen2.5-coder:7b-instruct",
        uses_rag=True,
        backend="ollama",
        description="Base Qwen2.5-Coder-7B-Instruct (Q4, with RAG)",
    ),
    "qwen3_coder": Variant(
        id="qwen3_coder",
        model_name="qwen3-coder-next:q4_K_M",
        uses_rag=False,
        backend="ollama",
        description="Qwen3-Coder-Next 80B-A3B MoE (Q4_K_M, no RAG)",
    ),
    "qwen3_coder_rag": Variant(
        id="qwen3_coder_rag",
        model_name="qwen3-coder-next:q4_K_M",
        uses_rag=True,
        backend="ollama",
        description="Qwen3-Coder-Next 80B-A3B MoE (Q4_K_M, with RAG)",
    ),
}

TEST_PRS = [
    {"number": 17418, "title": "pyproject.toml: Enforce trailing newline on python files", "domain": "build_system, code_style"},
    {"number": 18347, "title": "tests/extmod: Make test time_res.py more deterministic", "domain": "testing"},
    {"number": 18451, "title": "mimxrt: Fix SD card deadlock and timeout handling", "domain": "correctness, error_handling"},
    {"number": 18785, "title": "mpremote: Speed up file transfers with automatic encoding", "domain": "performance, tools"},
    {"number": 18416, "title": "py: Add enum support and minimal metaclass features", "domain": "api_design, architecture"},
]

# PR #18416 is the large one (71 files) — select substantive files only
LARGE_PR_MAX_FILES = 10

NUM_REPEATS = 3

BARE_TASK_INSTRUCTIONS = """# Your Task

Review this MicroPython pull request. You are a senior embedded systems developer reviewing code for the MicroPython project.

Focus on:
1. **Correctness**: Logic bugs, edge cases, error handling issues, race conditions
2. **Code Style**: MicroPython C and Python conventions (snake_case, proper macros, indentation)
3. **Memory Efficiency**: Embedded constraints — minimize heap allocations, avoid leaks
4. **API Design**: Clean interfaces, backwards compatibility, proper documentation
5. **Performance**: Unnecessary operations, algorithmic complexity
6. **Portability**: Cross-platform assumptions (endianness, pointer size, platform isolation)

For each issue found, classify its severity:
- **Blocking**: Must fix before merge (correctness bugs, security issues, data loss)
- **Suggestion**: Should fix for code quality (better patterns, clarity improvements)
- **Nitpick**: Minor style or consistency issues (formatting, naming)

Be direct and technical. Reference specific line numbers and code when possible. Do not pad your review with compliments or filler."""


def build_bare_prompt(pr_meta: dict, diff_text: str) -> str:
    """Build a bare prompt (no RAG context) for a PR review."""
    lines = [
        f"# Pull Request #{pr_meta['number']}",
        f"**Title**: {pr_meta['title']}",
        "",
        "## Diff",
        "",
        "```diff",
        diff_text,
        "```",
        "",
        BARE_TASK_INSTRUCTIONS,
    ]
    return "\n".join(lines)
