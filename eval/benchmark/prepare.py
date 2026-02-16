#!/usr/bin/env python3
"""Phase 1: Fetch expanded-context diffs and generate prompts for all variants.

Usage:
    python eval/benchmark/prepare.py [--clone-dir /tmp/micropython-bench]

This script:
1. Clones the MicroPython repo (if needed) and checks out each test PR
2. Generates expanded-context diffs (git diff -U200) for each PR
3. For the large PR (#18416), selects the most substantive files
4. Generates bare prompts (diff + task instructions)
5. Generates RAG prompts (style guide + examples + codebase + diff + task)
"""

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import click

from variants import TEST_PRS, LARGE_PR_MAX_FILES, build_bare_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BENCHMARK_DIR = Path(__file__).parent
DIFFS_DIR = BENCHMARK_DIR / "diffs"
PROMPTS_DIR = BENCHMARK_DIR / "prompts"


def run_cmd(args: list[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    logger.debug(f"Running: {' '.join(args)}")
    result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        logger.error(f"Command failed: {' '.join(args)}")
        logger.error(f"stderr: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)
    return result


def clone_repo(clone_dir: Path) -> Path:
    """Clone MicroPython repo if it doesn't exist."""
    if clone_dir.exists() and (clone_dir / ".git").exists():
        logger.info(f"Repo already exists at {clone_dir}, fetching latest...")
        run_cmd(["git", "fetch", "origin"], cwd=clone_dir)
        return clone_dir

    logger.info(f"Cloning MicroPython to {clone_dir}...")
    run_cmd(["git", "clone", "https://github.com/micropython/micropython.git", str(clone_dir)])
    return clone_dir


def get_pr_merge_base(repo_dir: Path, pr_number: int) -> str:
    """Checkout a PR and return the merge-base with main."""
    # Fetch the PR ref
    logger.info(f"Fetching PR #{pr_number}...")
    run_cmd(
        ["gh", "pr", "checkout", str(pr_number), "--repo", "micropython/micropython", "--force"],
        cwd=repo_dir,
    )

    # Find the merge base with main
    result = run_cmd(["git", "merge-base", "HEAD", "origin/master"], cwd=repo_dir)
    merge_base = result.stdout.strip()
    logger.info(f"PR #{pr_number}: merge-base = {merge_base[:12]}")
    return merge_base


def get_changed_files(repo_dir: Path, merge_base: str) -> list[dict]:
    """Get list of changed files with their diff sizes."""
    result = run_cmd(["git", "diff", "--stat", f"{merge_base}...HEAD"], cwd=repo_dir)
    # Also get the raw numstat for sorting by size
    numstat = run_cmd(["git", "diff", "--numstat", f"{merge_base}...HEAD"], cwd=repo_dir)

    files = []
    for line in numstat.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        try:
            total = int(added) + int(deleted)
        except ValueError:
            total = 0  # binary files
        files.append({"path": path, "added": added, "deleted": deleted, "total_changes": total})

    files.sort(key=lambda f: f["total_changes"], reverse=True)
    return files


def generate_expanded_diff(repo_dir: Path, merge_base: str, pr_number: int, files: list[dict]) -> str:
    """Generate expanded-context diff for a PR.

    For PRs with many files (like #18416), only include the most substantive files.
    Uses -U200 for 200 lines of context around each hunk.
    """
    num_files = len(files)

    if num_files > LARGE_PR_MAX_FILES:
        # Prioritize source code files over docs/logs
        source_exts = {".c", ".h", ".py", ".mk", ".cmake"}
        source_files = [f for f in files if Path(f["path"]).suffix in source_exts]
        other_files = [f for f in files if Path(f["path"]).suffix not in source_exts]
        # Fill with source files first, then other files if needed
        selected = (source_files + other_files)[:LARGE_PR_MAX_FILES]
        selected_paths = [f["path"] for f in selected]
        logger.info(
            f"PR #{pr_number}: {num_files} files changed, selecting top {LARGE_PR_MAX_FILES}: "
            f"{', '.join(selected_paths[:5])}..."
        )

        result = run_cmd(
            ["git", "diff", f"-U200", f"{merge_base}...HEAD", "--"] + selected_paths,
            cwd=repo_dir,
        )
        diff_text = result.stdout

        # Prepend a note about file selection
        header = (
            f"# NOTE: This PR modifies {num_files} files. "
            f"Showing the {LARGE_PR_MAX_FILES} most substantive files by change count.\n"
            f"# Selected files: {', '.join(selected_paths)}\n\n"
        )
        return header + diff_text
    else:
        # Full expanded diff
        result = run_cmd(
            ["git", "diff", "-U200", f"{merge_base}...HEAD"],
            cwd=repo_dir,
        )
        return result.stdout


def generate_rag_prompt(diff_text: str, pr_number: int) -> str:
    """Generate a RAG prompt using the existing mpy-reviewer pipeline.

    This pipes the expanded diff through the review command to get
    style guide + examples + codebase context + diff + task instructions.
    We use PromptBuilder directly with a high token limit to avoid truncation.
    """
    # Add project root to path so we can import rag
    project_root = BENCHMARK_DIR.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from rag.retriever import get_retriever
    from rag.reranker import get_reranker
    from rag.codebase import get_codebase_retriever
    from rag.prompt_builder import ReviewContext, PromptBuilder

    top_k = 8

    # Retrieve similar reviews using the diff as query
    logger.info(f"Retrieving similar reviews for PR #{pr_number}...")
    retriever = get_retriever()
    results = retriever.get_similar_reviews(diff_text, top_k=top_k * 2)

    # Re-rank
    logger.info("Re-ranking results...")
    reranker = get_reranker()
    results = reranker.rerank(diff_text, results, top_k=top_k)

    # Get codebase context (optional — codanna may not be available as Python module)
    codebase_context = None
    try:
        logger.info("Getting codebase context...")
        codebase_retriever = get_codebase_retriever()
        codebase_context = codebase_retriever.get_context_for_diff(diff_text, top_k=5)
    except (RuntimeError, ImportError) as e:
        logger.warning(f"Codebase context unavailable ({e}), continuing without it")

    # Build prompt manually to bypass PromptBuilder's 5000-char diff truncation.
    # We want the full expanded diff in the prompt.
    builder = PromptBuilder(max_context_tokens=200000)

    sections = []

    # Style guide
    sections.append(builder.STYLE_GUIDE)

    # Review examples
    context = ReviewContext(
        diff_text=diff_text,
        review_examples=results[:top_k],
        codebase_context=codebase_context,
        pr_number=pr_number,
    )
    examples_section = builder._format_review_examples(context.review_examples)
    if examples_section:
        sections.append(examples_section)

    # Codebase context
    if codebase_context:
        sections.append(builder._format_codebase_context(codebase_context))

    # Code to review — full diff, no truncation
    code_section = f"# Code to Review\n\n## PR #{pr_number}\n\n## Diff\n\n```diff\n{diff_text}\n```"
    sections.append(code_section)

    # Task description
    sections.append(builder._format_task_description())

    return "\n\n".join(sections)


@click.command()
@click.option(
    "--clone-dir",
    default="/tmp/micropython-bench",
    type=click.Path(),
    help="Directory to clone MicroPython repo into",
)
@click.option("--skip-clone", is_flag=True, help="Skip cloning, use existing repo")
@click.option("--pr", "single_pr", type=int, help="Only prepare a single PR (for testing)")
def main(clone_dir: str, skip_clone: bool, single_pr: Optional[int]):
    """Fetch expanded-context diffs and generate prompts for all test PRs."""
    clone_path = Path(clone_dir)

    DIFFS_DIR.mkdir(parents=True, exist_ok=True)
    (PROMPTS_DIR / "bare").mkdir(parents=True, exist_ok=True)
    (PROMPTS_DIR / "rag").mkdir(parents=True, exist_ok=True)

    # Clone repo
    if not skip_clone:
        clone_repo(clone_path)

    prs_to_process = TEST_PRS
    if single_pr:
        prs_to_process = [pr for pr in TEST_PRS if pr["number"] == single_pr]
        if not prs_to_process:
            logger.error(f"PR #{single_pr} not in test set")
            sys.exit(1)

    for pr in prs_to_process:
        pr_number = pr["number"]
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing PR #{pr_number}: {pr['title']}")
        logger.info(f"{'='*60}")

        diff_path = DIFFS_DIR / f"pr_{pr_number}.diff"
        bare_path = PROMPTS_DIR / "bare" / f"pr_{pr_number}.txt"
        rag_path = PROMPTS_DIR / "rag" / f"pr_{pr_number}.txt"

        # Step 1: Generate expanded diff
        if diff_path.exists():
            logger.info(f"Diff already cached: {diff_path}")
            diff_text = diff_path.read_text()
        else:
            merge_base = get_pr_merge_base(clone_path, pr_number)
            files = get_changed_files(clone_path, merge_base)
            logger.info(f"PR #{pr_number}: {len(files)} files changed")

            diff_text = generate_expanded_diff(clone_path, merge_base, pr_number, files)
            diff_path.write_text(diff_text)
            logger.info(f"Saved diff: {diff_path} ({len(diff_text)} chars)")

        # Step 2: Generate bare prompt
        if bare_path.exists():
            logger.info(f"Bare prompt already cached: {bare_path}")
        else:
            bare_prompt = build_bare_prompt(pr, diff_text)
            bare_path.write_text(bare_prompt)
            logger.info(f"Saved bare prompt: {bare_path} ({len(bare_prompt)} chars)")

        # Step 3: Generate RAG prompt
        if rag_path.exists():
            logger.info(f"RAG prompt already cached: {rag_path}")
        else:
            start = time.time()
            rag_prompt = generate_rag_prompt(diff_text, pr_number)
            elapsed = time.time() - start
            rag_path.write_text(rag_prompt)
            logger.info(f"Saved RAG prompt: {rag_path} ({len(rag_prompt)} chars, {elapsed:.1f}s)")

        # Return to main branch for next PR
        run_cmd(["git", "checkout", "origin/master", "--force"], cwd=clone_path, check=False)

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("Preparation complete!")
    logger.info(f"{'='*60}")
    for pr in prs_to_process:
        pr_number = pr["number"]
        diff_path = DIFFS_DIR / f"pr_{pr_number}.diff"
        bare_path = PROMPTS_DIR / "bare" / f"pr_{pr_number}.txt"
        rag_path = PROMPTS_DIR / "rag" / f"pr_{pr_number}.txt"
        logger.info(
            f"PR #{pr_number}: diff={diff_path.stat().st_size:,}B  "
            f"bare={bare_path.stat().st_size:,}B  "
            f"rag={rag_path.stat().st_size:,}B"
        )


if __name__ == "__main__":
    main()
