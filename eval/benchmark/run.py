#!/usr/bin/env python3
"""Phase 2: Execute all benchmark variants and save review outputs.

Usage:
    # Run all variants
    python eval/benchmark/run.py

    # Run specific variants
    python eval/benchmark/run.py --variants ft_f16,sonnet_bare

    # Run a single PR for testing
    python eval/benchmark/run.py --variants sonnet_bare --prs 18347 --repeats 1

    # Ollama variants (requires SSH tunnel: ssh -L 11435:localhost:11434 piai)
    python eval/benchmark/run.py --variants ft_f16,ft_q4,ft_f16_rag

    # Claude variants (can run in parallel)
    python eval/benchmark/run.py --variants sonnet_bare,opus_bare,sonnet_rag,opus_rag
"""

import json
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from variants import VARIANTS, TEST_PRS, NUM_REPEATS, Variant

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BENCHMARK_DIR = Path(__file__).parent
PROMPTS_DIR = BENCHMARK_DIR / "prompts"
RESULTS_DIR = BENCHMARK_DIR / "results"

OLLAMA_URL = "http://localhost:11435/api/generate"
OLLAMA_NUM_CTX = 32768
OLLAMA_TEMPERATURE = 0.7

CLAUDE_MAX_BUDGET = 0.50
CLAUDE_MAX_PARALLEL = 3

# All tools to disable for Claude (static prompt, no tool use)
CLAUDE_DISALLOWED_TOOLS = ",".join([
    "Bash", "Read", "Write", "Edit", "Glob", "Grep",
    "Task", "WebFetch", "WebSearch", "NotebookEdit",
])


def result_path(variant_id: str, pr_number: int, run: int) -> Path:
    """Get the output path for a specific (variant, PR, run) tuple."""
    d = RESULTS_DIR / variant_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"pr_{pr_number}_run{run}.json"


def load_prompt(variant: Variant, pr_number: int) -> str:
    """Load the pre-generated prompt for a variant/PR combination."""
    prompt_type = variant.prompt_type
    path = PROMPTS_DIR / prompt_type / f"pr_{pr_number}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"Prompt not found: {path}. Run prepare.py first."
        )
    return path.read_text()


def run_ollama(variant: Variant, prompt: str, pr_number: int, run_num: int) -> dict:
    """Run an Ollama variant and return the result."""
    import requests

    logger.info(f"[{variant.id}] PR #{pr_number} run {run_num}: calling Ollama ({variant.model_name})...")

    start = time.time()
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": variant.model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": OLLAMA_TEMPERATURE,
                    "num_ctx": OLLAMA_NUM_CTX,
                },
            },
            timeout=600,  # 10 minute timeout
        )
        resp.raise_for_status()
        data = resp.json()
        response_text = data.get("response", "")
        duration_ms = (time.time() - start) * 1000

        logger.info(
            f"[{variant.id}] PR #{pr_number} run {run_num}: "
            f"{len(response_text)} chars in {duration_ms:.0f}ms"
        )

        return {
            "variant": variant.id,
            "pr_number": pr_number,
            "run": run_num,
            "response": response_text,
            "duration_ms": round(duration_ms, 2),
            "model": variant.model_name,
            "backend": "ollama",
            "timestamp": datetime.now().isoformat(),
            "prompt_chars": len(prompt),
            "response_chars": len(response_text),
            "ollama_metrics": {
                k: v for k, v in data.items() if k != "response"
            },
            "error": None,
        }
    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        logger.error(f"[{variant.id}] PR #{pr_number} run {run_num}: ERROR: {e}")
        return {
            "variant": variant.id,
            "pr_number": pr_number,
            "run": run_num,
            "response": "",
            "duration_ms": round(duration_ms, 2),
            "model": variant.model_name,
            "backend": "ollama",
            "timestamp": datetime.now().isoformat(),
            "prompt_chars": len(prompt),
            "response_chars": 0,
            "error": str(e),
        }


def run_claude(variant: Variant, prompt: str, pr_number: int, run_num: int) -> dict:
    """Run a Claude variant via `claude -p` and return the result."""
    logger.info(f"[{variant.id}] PR #{pr_number} run {run_num}: calling Claude ({variant.claude_model})...")

    start = time.time()
    try:
        cmd = [
            "claude", "-p",
            "--model", variant.claude_model,
            "--output-format", "json",
            "--disallowed-tools", CLAUDE_DISALLOWED_TOOLS,
            "--max-budget-usd", str(CLAUDE_MAX_BUDGET),
        ]

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        duration_ms = (time.time() - start) * 1000

        if result.returncode != 0:
            logger.error(f"[{variant.id}] PR #{pr_number} run {run_num}: claude failed: {result.stderr}")
            return {
                "variant": variant.id,
                "pr_number": pr_number,
                "run": run_num,
                "response": "",
                "duration_ms": round(duration_ms, 2),
                "model": variant.model_name,
                "backend": "claude",
                "timestamp": datetime.now().isoformat(),
                "prompt_chars": len(prompt),
                "response_chars": 0,
                "error": f"claude exit code {result.returncode}: {result.stderr[:500]}",
            }

        # Parse JSON output from claude
        try:
            claude_output = json.loads(result.stdout)
            response_text = claude_output.get("result", result.stdout)
        except json.JSONDecodeError:
            # If JSON parsing fails, use raw stdout
            response_text = result.stdout

        logger.info(
            f"[{variant.id}] PR #{pr_number} run {run_num}: "
            f"{len(response_text)} chars in {duration_ms:.0f}ms"
        )

        return {
            "variant": variant.id,
            "pr_number": pr_number,
            "run": run_num,
            "response": response_text,
            "duration_ms": round(duration_ms, 2),
            "model": variant.model_name,
            "backend": "claude",
            "timestamp": datetime.now().isoformat(),
            "prompt_chars": len(prompt),
            "response_chars": len(response_text),
            "error": None,
        }
    except subprocess.TimeoutExpired:
        duration_ms = (time.time() - start) * 1000
        logger.error(f"[{variant.id}] PR #{pr_number} run {run_num}: TIMEOUT after {duration_ms:.0f}ms")
        return {
            "variant": variant.id,
            "pr_number": pr_number,
            "run": run_num,
            "response": "",
            "duration_ms": round(duration_ms, 2),
            "model": variant.model_name,
            "backend": "claude",
            "timestamp": datetime.now().isoformat(),
            "prompt_chars": len(prompt),
            "response_chars": 0,
            "error": "timeout",
        }
    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        logger.error(f"[{variant.id}] PR #{pr_number} run {run_num}: ERROR: {e}")
        return {
            "variant": variant.id,
            "pr_number": pr_number,
            "run": run_num,
            "response": "",
            "duration_ms": round(duration_ms, 2),
            "model": variant.model_name,
            "backend": "claude",
            "timestamp": datetime.now().isoformat(),
            "prompt_chars": len(prompt),
            "response_chars": 0,
            "error": str(e),
        }


def run_single(variant: Variant, pr_number: int, run_num: int) -> dict:
    """Run a single (variant, PR, run) and save the result."""
    out_path = result_path(variant.id, pr_number, run_num)

    # Skip if already completed
    if out_path.exists():
        existing = json.loads(out_path.read_text())
        if existing.get("response") and not existing.get("error"):
            logger.info(f"[{variant.id}] PR #{pr_number} run {run_num}: already completed, skipping")
            return existing

    prompt = load_prompt(variant, pr_number)

    if variant.backend == "ollama":
        result = run_ollama(variant, prompt, pr_number, run_num)
    elif variant.backend == "claude":
        result = run_claude(variant, prompt, pr_number, run_num)
    else:
        raise ValueError(f"Unknown backend: {variant.backend}")

    # Save result
    out_path.write_text(json.dumps(result, indent=2))
    logger.info(f"Saved: {out_path}")

    return result


def run_variants_sequential(variant_ids: list[str], pr_numbers: list[int], repeats: int):
    """Run variants sequentially (for Ollama / single-GPU)."""
    total = len(variant_ids) * len(pr_numbers) * repeats
    completed = 0
    errors = 0

    for vid in variant_ids:
        variant = VARIANTS[vid]
        for pr in pr_numbers:
            for run_num in range(1, repeats + 1):
                result = run_single(variant, pr, run_num)
                completed += 1
                if result.get("error"):
                    errors += 1
                logger.info(f"Progress: {completed}/{total} (errors: {errors})")

    return completed, errors


def run_variants_parallel(variant_ids: list[str], pr_numbers: list[int], repeats: int, max_workers: int = 3):
    """Run Claude variants in parallel."""
    tasks = []
    for vid in variant_ids:
        variant = VARIANTS[vid]
        for pr in pr_numbers:
            for run_num in range(1, repeats + 1):
                tasks.append((variant, pr, run_num))

    total = len(tasks)
    completed = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_single, variant, pr, run_num): (variant.id, pr, run_num)
            for variant, pr, run_num in tasks
        }

        for future in as_completed(futures):
            vid, pr, run_num = futures[future]
            try:
                result = future.result()
                if result.get("error"):
                    errors += 1
            except Exception as e:
                logger.error(f"[{vid}] PR #{pr} run {run_num}: unhandled exception: {e}")
                errors += 1

            completed += 1
            logger.info(f"Progress: {completed}/{total} (errors: {errors})")

    return completed, errors


@click.command()
@click.option(
    "--variants",
    default=None,
    help="Comma-separated variant IDs (default: all)",
)
@click.option(
    "--prs",
    default=None,
    help="Comma-separated PR numbers (default: all test PRs)",
)
@click.option(
    "--repeats",
    default=NUM_REPEATS,
    type=int,
    help=f"Number of repeats per (variant, PR) (default: {NUM_REPEATS})",
)
@click.option(
    "--parallel/--sequential",
    default=None,
    help="Force parallel or sequential execution (default: auto based on backend)",
)
def main(variants: Optional[str], prs: Optional[str], repeats: int, parallel: Optional[bool]):
    """Execute benchmark variants and save review outputs."""
    # Parse variant IDs
    if variants:
        variant_ids = [v.strip() for v in variants.split(",")]
        for vid in variant_ids:
            if vid not in VARIANTS:
                logger.error(f"Unknown variant: {vid}")
                logger.info(f"Available: {', '.join(VARIANTS.keys())}")
                sys.exit(1)
    else:
        variant_ids = list(VARIANTS.keys())

    # Parse PR numbers
    if prs:
        pr_numbers = [int(p.strip()) for p in prs.split(",")]
    else:
        pr_numbers = [pr["number"] for pr in TEST_PRS]

    # Check prompts exist
    for vid in variant_ids:
        variant = VARIANTS[vid]
        for pr_number in pr_numbers:
            prompt_path = PROMPTS_DIR / variant.prompt_type / f"pr_{pr_number}.txt"
            if not prompt_path.exists():
                logger.error(f"Missing prompt: {prompt_path}. Run prepare.py first.")
                sys.exit(1)

    total = len(variant_ids) * len(pr_numbers) * repeats
    logger.info(f"Benchmark: {len(variant_ids)} variants x {len(pr_numbers)} PRs x {repeats} repeats = {total} reviews")
    logger.info(f"Variants: {', '.join(variant_ids)}")
    logger.info(f"PRs: {', '.join(str(p) for p in pr_numbers)}")

    # Determine execution mode
    backends = {VARIANTS[vid].backend for vid in variant_ids}

    if parallel is None:
        # Auto: parallel for Claude-only, sequential for Ollama or mixed
        if backends == {"claude"}:
            parallel = True
        else:
            parallel = False

    start = time.time()

    if parallel:
        logger.info(f"Running in parallel mode (max {CLAUDE_MAX_PARALLEL} workers)")
        completed, errors = run_variants_parallel(variant_ids, pr_numbers, repeats, CLAUDE_MAX_PARALLEL)
    else:
        logger.info("Running in sequential mode")
        completed, errors = run_variants_sequential(variant_ids, pr_numbers, repeats)

    elapsed = time.time() - start

    logger.info(f"\n{'='*60}")
    logger.info(f"Benchmark run complete!")
    logger.info(f"Completed: {completed}/{total} ({errors} errors)")
    logger.info(f"Elapsed: {elapsed:.0f}s ({elapsed/60:.1f}min)")
    logger.info(f"Results saved to: {RESULTS_DIR}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
