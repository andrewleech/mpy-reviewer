#!/usr/bin/env python3
"""Phase 3: LLM-as-judge scoring of all benchmark review outputs.

Usage:
    # Score all results
    python eval/benchmark/judge.py

    # Score a single variant for testing
    python eval/benchmark/judge.py --variants sonnet_bare --prs 18347

    # Skip consistency pass
    python eval/benchmark/judge.py --skip-consistency

    # Re-score (overwrite existing scores)
    python eval/benchmark/judge.py --force
"""

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import click

from variants import VARIANTS, TEST_PRS, NUM_REPEATS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BENCHMARK_DIR = Path(__file__).parent
DIFFS_DIR = BENCHMARK_DIR / "diffs"
RESULTS_DIR = BENCHMARK_DIR / "results"
SCORES_DIR = BENCHMARK_DIR / "scores"

JUDGE_MODEL = "opus"

SCORING_CRITERIA = """## Scoring Criteria

Rate each criterion from 1 to 5:

### 1. Technical Accuracy (1-5)
- **1**: Multiple factually wrong claims, suggestions that would introduce bugs
- **3**: Mostly correct, one or two minor inaccuracies or vague claims
- **5**: All identified issues are real; suggestions are technically sound

### 2. Relevance (1-5)
- **1**: Review focuses on trivial or irrelevant aspects, misses the point of the change
- **3**: Covers some important aspects but also includes off-topic or low-value points
- **5**: Laser-focused on the most important aspects of the change

### 3. Completeness (1-5)
- **1**: Misses most significant issues in the diff
- **3**: Catches some major issues but overlooks others
- **5**: Identifies all significant issues; thorough coverage

### 4. Actionability (1-5)
- **1**: Vague complaints with no clear path to resolution ("this could be better")
- **3**: Some suggestions are actionable, others are too vague to act on
- **5**: Every suggestion is specific, references exact code, and explains what to do

### 5. Style Fidelity (1-5)
How well does this match dpgeorge's review style?
- **1**: Overly verbose, uses filler/compliments, corporate tone, or generic advice
- **3**: Somewhat technical and direct, but occasionally padded or generic
- **5**: Direct, terse, technically precise. No filler. Points are concise and specific.

### 6. Severity Calibration (1-5)
- **1**: Severity levels are wildly off (nitpicks marked blocking, real bugs marked nitpick)
- **3**: Mostly reasonable but some miscalibrations
- **5**: Severity assignments match the actual impact of each issue"""

SCORING_SCHEMA = {
    "type": "object",
    "properties": {
        "technical_accuracy": {"type": "integer", "minimum": 1, "maximum": 5},
        "relevance": {"type": "integer", "minimum": 1, "maximum": 5},
        "completeness": {"type": "integer", "minimum": 1, "maximum": 5},
        "actionability": {"type": "integer", "minimum": 1, "maximum": 5},
        "style_fidelity": {"type": "integer", "minimum": 1, "maximum": 5},
        "severity_calibration": {"type": "integer", "minimum": 1, "maximum": 5},
        "brief_justification": {"type": "string"},
    },
    "required": [
        "technical_accuracy", "relevance", "completeness",
        "actionability", "style_fidelity", "severity_calibration",
        "brief_justification",
    ],
}

CONSISTENCY_SCHEMA = {
    "type": "object",
    "properties": {
        "consistency": {"type": "integer", "minimum": 1, "maximum": 5},
        "consistency_notes": {"type": "string"},
        "best_run": {"type": "string", "enum": ["A", "B", "C"]},
        "best_reason": {"type": "string"},
        "worst_run": {"type": "string", "enum": ["A", "B", "C"]},
        "worst_reason": {"type": "string"},
    },
    "required": [
        "consistency", "consistency_notes",
        "best_run", "best_reason",
        "worst_run", "worst_reason",
    ],
}


def score_path(variant_id: str, pr_number: int, run_num: int) -> Path:
    """Get the score output path for a specific (variant, PR, run) tuple."""
    d = SCORES_DIR / variant_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"pr_{pr_number}_run{run_num}.json"


def consistency_path(variant_id: str, pr_number: int) -> Path:
    """Get the consistency score path for a (variant, PR) group."""
    d = SCORES_DIR / variant_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"pr_{pr_number}_consistency.json"


def call_judge(prompt: str, schema: dict) -> dict:
    """Call Claude as judge via `claude -p` with JSON schema enforcement."""
    cmd = [
        "claude", "-p",
        "--model", JUDGE_MODEL,
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--tools", "",
        "--append-system-prompt", "Output your evaluation as JSON. Do not attempt to use any tools, skills, or commands.",
        "--max-budget-usd", "1.00",
    ]

    import os
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"claude judge failed: {result.stderr[:500]}")

    # Parse the JSON output from claude -p --output-format json --json-schema
    # Format: {"type":"result", "structured_output": {...}, "result": "", ...}
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Could not parse claude output as JSON: {result.stdout[:500]}")

    # --json-schema puts structured output in the "structured_output" field
    if isinstance(output, dict) and "structured_output" in output:
        structured = output["structured_output"]
        if isinstance(structured, dict):
            return structured

    # Fallback: check "result" field (may contain JSON string)
    if isinstance(output, dict) and "result" in output:
        result_val = output["result"]
        if isinstance(result_val, dict):
            return result_val
        if isinstance(result_val, str) and result_val.strip():
            return json.loads(result_val)

    raise RuntimeError(f"No structured output in judge response: {json.dumps(output)[:500]}")


def score_single_review(variant_id: str, pr_number: int, run_num: int, force: bool = False) -> Optional[dict]:
    """Score a single review output."""
    out = score_path(variant_id, pr_number, run_num)

    if out.exists() and not force:
        logger.info(f"[{variant_id}] PR #{pr_number} run {run_num}: already scored, skipping")
        return json.loads(out.read_text())

    # Load the review result
    result_file = RESULTS_DIR / variant_id / f"pr_{pr_number}_run{run_num}.json"
    if not result_file.exists():
        logger.warning(f"[{variant_id}] PR #{pr_number} run {run_num}: no result file, skipping")
        return None

    result = json.loads(result_file.read_text())
    if result.get("error") or not result.get("response"):
        logger.warning(f"[{variant_id}] PR #{pr_number} run {run_num}: error in result, skipping")
        return None

    # Load the diff
    diff_file = DIFFS_DIR / f"pr_{pr_number}.diff"
    diff_text = diff_file.read_text()
    # Truncate diff for judge context if very large
    if len(diff_text) > 30000:
        diff_text = diff_text[:30000] + "\n\n... (diff truncated for judge context)"

    # Build judge prompt
    prompt = f"""You are evaluating a code review of MicroPython pull request #{pr_number}.

The reviewer was asked to review the following diff and provide dpgeorge-style feedback.

## PR Diff

```diff
{diff_text}
```

## Review Being Evaluated

{result['response']}

{SCORING_CRITERIA}

Score the review on all 6 criteria. Provide a brief justification (2-3 sentences) covering the most notable strengths or weaknesses.

Respond with JSON matching the schema."""

    logger.info(f"[{variant_id}] PR #{pr_number} run {run_num}: scoring...")
    start = time.time()

    try:
        scores = call_judge(prompt, SCORING_SCHEMA)
        elapsed = time.time() - start

        # Add metadata
        scores["variant"] = variant_id
        scores["pr_number"] = pr_number
        scores["run"] = run_num
        scores["judge_duration_ms"] = round(elapsed * 1000, 2)
        scores["judge_model"] = JUDGE_MODEL
        scores["mean_score"] = round(
            sum(scores[k] for k in [
                "technical_accuracy", "relevance", "completeness",
                "actionability", "style_fidelity", "severity_calibration",
            ]) / 6, 2
        )

        out.write_text(json.dumps(scores, indent=2))
        logger.info(
            f"[{variant_id}] PR #{pr_number} run {run_num}: "
            f"mean={scores['mean_score']:.2f} ({elapsed:.1f}s)"
        )
        return scores

    except Exception as e:
        logger.error(f"[{variant_id}] PR #{pr_number} run {run_num}: judge error: {e}")
        return None


def score_consistency(variant_id: str, pr_number: int, force: bool = False) -> Optional[dict]:
    """Score consistency across 3 repeats for a (variant, PR) group."""
    out = consistency_path(variant_id, pr_number)

    if out.exists() and not force:
        logger.info(f"[{variant_id}] PR #{pr_number}: consistency already scored, skipping")
        return json.loads(out.read_text())

    # Load all 3 review outputs
    reviews = {}
    labels = ["A", "B", "C"]
    for run_num, label in zip(range(1, NUM_REPEATS + 1), labels):
        result_file = RESULTS_DIR / variant_id / f"pr_{pr_number}_run{run_num}.json"
        if not result_file.exists():
            logger.warning(f"[{variant_id}] PR #{pr_number}: missing run {run_num}, skipping consistency")
            return None
        result = json.loads(result_file.read_text())
        if result.get("error") or not result.get("response"):
            logger.warning(f"[{variant_id}] PR #{pr_number}: run {run_num} has error, skipping consistency")
            return None
        reviews[label] = result["response"]

    # Build consistency prompt
    sections = []
    for label in labels:
        sections.append(f"## Review {label}\n\n{reviews[label]}")

    prompt = f"""You are comparing 3 reviews of the same MicroPython pull request #{pr_number}, all generated by the same model ({variant_id}).

Assess how consistent the reviews are across the 3 runs, and identify the best and worst.

{chr(10).join(sections)}

## Assessment

Rate consistency from 1 to 5:
- **1**: Reviews contradict each other or focus on completely different aspects
- **3**: Reviews share some common themes but differ significantly in coverage/detail
- **5**: Reviews are highly consistent — same issues identified, similar severity, similar structure

Identify the best review (highest quality) and worst review (lowest quality), with brief reasons.

Respond with JSON matching the schema."""

    logger.info(f"[{variant_id}] PR #{pr_number}: scoring consistency...")
    start = time.time()

    try:
        scores = call_judge(prompt, CONSISTENCY_SCHEMA)
        elapsed = time.time() - start

        scores["variant"] = variant_id
        scores["pr_number"] = pr_number
        scores["judge_duration_ms"] = round(elapsed * 1000, 2)
        scores["judge_model"] = JUDGE_MODEL

        out.write_text(json.dumps(scores, indent=2))
        logger.info(
            f"[{variant_id}] PR #{pr_number}: consistency={scores['consistency']} "
            f"best={scores['best_run']} worst={scores['worst_run']} ({elapsed:.1f}s)"
        )
        return scores

    except Exception as e:
        logger.error(f"[{variant_id}] PR #{pr_number}: consistency judge error: {e}")
        return None


@click.command()
@click.option("--variants", default=None, help="Comma-separated variant IDs (default: all with results)")
@click.option("--prs", default=None, help="Comma-separated PR numbers (default: all)")
@click.option("--skip-consistency", is_flag=True, help="Skip the consistency analysis pass")
@click.option("--force", is_flag=True, help="Re-score even if scores already exist")
def main(variants: Optional[str], prs: Optional[str], skip_consistency: bool, force: bool):
    """Score all benchmark review outputs using LLM-as-judge."""
    SCORES_DIR.mkdir(parents=True, exist_ok=True)

    # Determine which variants to score
    if variants:
        variant_ids = [v.strip() for v in variants.split(",")]
    else:
        # Auto-detect from results directory
        variant_ids = []
        if RESULTS_DIR.exists():
            for d in sorted(RESULTS_DIR.iterdir()):
                if d.is_dir() and d.name in VARIANTS:
                    variant_ids.append(d.name)
        if not variant_ids:
            logger.error("No results found. Run run.py first.")
            sys.exit(1)

    # Parse PR numbers
    if prs:
        pr_numbers = [int(p.strip()) for p in prs.split(",")]
    else:
        pr_numbers = [pr["number"] for pr in TEST_PRS]

    # Pass 1: Individual scoring
    logger.info(f"Pass 1: Scoring individual reviews")
    logger.info(f"Variants: {', '.join(variant_ids)}")
    logger.info(f"PRs: {', '.join(str(p) for p in pr_numbers)}")

    total_scored = 0
    total_errors = 0
    start = time.time()

    for vid in variant_ids:
        for pr_number in pr_numbers:
            for run_num in range(1, NUM_REPEATS + 1):
                result = score_single_review(vid, pr_number, run_num, force=force)
                if result is not None:
                    total_scored += 1
                else:
                    total_errors += 1

    pass1_elapsed = time.time() - start
    logger.info(f"Pass 1 complete: {total_scored} scored, {total_errors} errors/skipped ({pass1_elapsed:.0f}s)")

    # Pass 2: Consistency analysis
    if not skip_consistency:
        logger.info(f"\nPass 2: Consistency analysis")
        consistency_count = 0
        start = time.time()

        for vid in variant_ids:
            for pr_number in pr_numbers:
                result = score_consistency(vid, pr_number, force=force)
                if result is not None:
                    consistency_count += 1

        pass2_elapsed = time.time() - start
        logger.info(f"Pass 2 complete: {consistency_count} groups scored ({pass2_elapsed:.0f}s)")

    logger.info(f"\nScoring complete! Results in: {SCORES_DIR}")


if __name__ == "__main__":
    main()
