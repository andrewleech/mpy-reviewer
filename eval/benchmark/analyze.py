#!/usr/bin/env python3
"""Phase 4: Aggregate scores and generate the benchmark report.

Usage:
    python eval/benchmark/analyze.py
"""

import json
import logging
import statistics
from collections import defaultdict
from pathlib import Path

import click

from variants import VARIANTS, TEST_PRS, NUM_REPEATS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BENCHMARK_DIR = Path(__file__).parent
RESULTS_DIR = BENCHMARK_DIR / "results"
SCORES_DIR = BENCHMARK_DIR / "scores"
REPORT_DIR = BENCHMARK_DIR / "report"

CRITERIA = [
    "technical_accuracy",
    "relevance",
    "completeness",
    "actionability",
    "style_fidelity",
    "severity_calibration",
]

CRITERIA_SHORT = {
    "technical_accuracy": "Tech Acc",
    "relevance": "Relevance",
    "completeness": "Complete",
    "actionability": "Action",
    "style_fidelity": "Style",
    "severity_calibration": "Severity",
}


def load_all_scores() -> dict:
    """Load all individual scores from the scores directory.

    Returns dict keyed by (variant, pr, run) -> score dict.
    """
    scores = {}
    if not SCORES_DIR.exists():
        return scores

    for variant_dir in SCORES_DIR.iterdir():
        if not variant_dir.is_dir():
            continue
        vid = variant_dir.name
        for f in variant_dir.glob("pr_*_run*.json"):
            data = json.loads(f.read_text())
            key = (vid, data["pr_number"], data["run"])
            scores[key] = data

    return scores


def load_all_consistency() -> dict:
    """Load all consistency scores.

    Returns dict keyed by (variant, pr) -> consistency dict.
    """
    consistency = {}
    if not SCORES_DIR.exists():
        return consistency

    for variant_dir in SCORES_DIR.iterdir():
        if not variant_dir.is_dir():
            continue
        vid = variant_dir.name
        for f in variant_dir.glob("pr_*_consistency.json"):
            data = json.loads(f.read_text())
            key = (vid, data["pr_number"])
            consistency[key] = data

    return consistency


def load_all_results() -> dict:
    """Load all raw results (review outputs) for duration/metadata analysis."""
    results = {}
    if not RESULTS_DIR.exists():
        return results

    for variant_dir in RESULTS_DIR.iterdir():
        if not variant_dir.is_dir():
            continue
        vid = variant_dir.name
        for f in variant_dir.glob("pr_*_run*.json"):
            data = json.loads(f.read_text())
            key = (vid, data["pr_number"], data["run"])
            results[key] = data

    return results


def mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def stdev(values: list[float]) -> float:
    return statistics.stdev(values) if len(values) >= 2 else 0.0


def fmt(val: float, decimals: int = 2) -> str:
    return f"{val:.{decimals}f}"


def generate_report(scores: dict, consistency: dict, results: dict) -> str:
    """Generate the full markdown report."""
    lines = ["# Benchmark: Fine-Tuned Model vs Claude + RAG for Code Review", ""]
    lines.append(f"Generated from {len(scores)} scored reviews across {len(VARIANTS)} variants and {len(TEST_PRS)} PRs.")
    lines.append("")

    # 1. Overall variant comparison
    lines.append("## Overall Variant Comparison")
    lines.append("")

    # Collect per-variant aggregates
    variant_agg = {}
    for vid in VARIANTS:
        variant_scores = [s for (v, p, r), s in scores.items() if v == vid]
        if not variant_scores:
            continue

        agg = {"n": len(variant_scores)}
        for criterion in CRITERIA:
            vals = [s[criterion] for s in variant_scores]
            agg[f"{criterion}_mean"] = mean(vals)
            agg[f"{criterion}_std"] = stdev(vals)

        mean_scores = [s["mean_score"] for s in variant_scores]
        agg["overall_mean"] = mean(mean_scores)
        agg["overall_std"] = stdev(mean_scores)
        variant_agg[vid] = agg

    # Sort by overall mean descending
    sorted_variants = sorted(variant_agg.keys(), key=lambda v: variant_agg[v]["overall_mean"], reverse=True)

    # Table header
    header = "| Variant | n |"
    for c in CRITERIA:
        header += f" {CRITERIA_SHORT[c]} |"
    header += " **Mean** |"
    lines.append(header)

    sep = "|---------|---|"
    for _ in CRITERIA:
        sep += "--------|"
    sep += "---------|"
    lines.append(sep)

    for vid in sorted_variants:
        agg = variant_agg[vid]
        row = f"| {vid} | {agg['n']} |"
        for c in CRITERIA:
            m = agg[f"{c}_mean"]
            s = agg[f"{c}_std"]
            row += f" {fmt(m)}{chr(177)}{fmt(s, 1)} |"
        row += f" **{fmt(agg['overall_mean'])}**{chr(177)}{fmt(agg['overall_std'], 1)} |"
        lines.append(row)

    lines.append("")

    # 2. Per-PR comparison
    lines.append("## Per-PR Comparison")
    lines.append("")

    pr_lookup = {pr["number"]: pr for pr in TEST_PRS}

    for pr_info in TEST_PRS:
        pr_num = pr_info["number"]
        lines.append(f"### PR #{pr_num}: {pr_info['title']}")
        lines.append(f"Domain: {pr_info['domain']}")
        lines.append("")

        header = "| Variant |"
        for c in CRITERIA:
            header += f" {CRITERIA_SHORT[c]} |"
        header += " Mean |"
        lines.append(header)

        sep = "|---------|"
        for _ in CRITERIA:
            sep += "--------|"
        sep += "------|"
        lines.append(sep)

        pr_variant_means = {}
        for vid in sorted_variants:
            pr_scores = [s for (v, p, r), s in scores.items() if v == vid and p == pr_num]
            if not pr_scores:
                continue

            row = f"| {vid} |"
            for c in CRITERIA:
                vals = [s[c] for s in pr_scores]
                row += f" {fmt(mean(vals))} |"
            mean_val = mean([s["mean_score"] for s in pr_scores])
            row += f" {fmt(mean_val)} |"
            lines.append(row)
            pr_variant_means[vid] = mean_val

        if pr_variant_means:
            best = max(pr_variant_means, key=pr_variant_means.get)
            lines.append(f"\nBest: **{best}** ({fmt(pr_variant_means[best])})")

        lines.append("")

    # 3. RAG impact analysis
    lines.append("## RAG Impact Analysis")
    lines.append("")
    lines.append("Delta between RAG and bare variants for the same base model.")
    lines.append("")

    rag_pairs = [
        ("sonnet_bare", "sonnet_rag", "Sonnet 4.5"),
        ("opus_bare", "opus_rag", "Opus 4.6"),
        ("ft_f16", "ft_f16_rag", "Fine-tuned F16"),
    ]

    header = "| Model | Criterion | Bare | RAG | Delta |"
    lines.append(header)
    lines.append("|-------|-----------|------|-----|-------|")

    for bare_id, rag_id, label in rag_pairs:
        if bare_id not in variant_agg or rag_id not in variant_agg:
            continue

        for c in CRITERIA:
            bare_val = variant_agg[bare_id][f"{c}_mean"]
            rag_val = variant_agg[rag_id][f"{c}_mean"]
            delta = rag_val - bare_val
            sign = "+" if delta >= 0 else ""
            lines.append(f"| {label} | {CRITERIA_SHORT[c]} | {fmt(bare_val)} | {fmt(rag_val)} | {sign}{fmt(delta)} |")

        bare_overall = variant_agg[bare_id]["overall_mean"]
        rag_overall = variant_agg[rag_id]["overall_mean"]
        delta = rag_overall - bare_overall
        sign = "+" if delta >= 0 else ""
        lines.append(f"| **{label}** | **Overall** | **{fmt(bare_overall)}** | **{fmt(rag_overall)}** | **{sign}{fmt(delta)}** |")

    lines.append("")

    # 4. Quantization impact
    lines.append("## Quantization Impact (F16 vs Q4)")
    lines.append("")

    if "ft_f16" in variant_agg and "ft_q4" in variant_agg:
        header = "| Criterion | F16 | Q4_K_M | Delta |"
        lines.append(header)
        lines.append("|-----------|-----|--------|-------|")

        for c in CRITERIA:
            f16_val = variant_agg["ft_f16"][f"{c}_mean"]
            q4_val = variant_agg["ft_q4"][f"{c}_mean"]
            delta = q4_val - f16_val
            sign = "+" if delta >= 0 else ""
            lines.append(f"| {CRITERIA_SHORT[c]} | {fmt(f16_val)} | {fmt(q4_val)} | {sign}{fmt(delta)} |")

        f16_overall = variant_agg["ft_f16"]["overall_mean"]
        q4_overall = variant_agg["ft_q4"]["overall_mean"]
        delta = q4_overall - f16_overall
        sign = "+" if delta >= 0 else ""
        lines.append(f"| **Overall** | **{fmt(f16_overall)}** | **{fmt(q4_overall)}** | **{sign}{fmt(delta)}** |")
    else:
        lines.append("*Insufficient data for quantization comparison.*")

    lines.append("")

    # 5. Consistency analysis
    lines.append("## Consistency Across Repeats")
    lines.append("")

    if consistency:
        header = "| Variant | PR | Consistency | Best | Worst | Notes |"
        lines.append(header)
        lines.append("|---------|-----|-------------|------|-------|-------|")

        for vid in sorted_variants:
            for pr_info in TEST_PRS:
                pr_num = pr_info["number"]
                key = (vid, pr_num)
                if key not in consistency:
                    continue
                c = consistency[key]
                notes = c.get("consistency_notes", "")[:80]
                lines.append(
                    f"| {vid} | #{pr_num} | {c['consistency']}/5 | "
                    f"Run {c['best_run']} | Run {c['worst_run']} | {notes} |"
                )

        lines.append("")

        # Aggregate consistency per variant
        lines.append("### Mean Consistency by Variant")
        lines.append("")
        lines.append("| Variant | Mean Consistency | Std |")
        lines.append("|---------|-----------------|-----|")

        for vid in sorted_variants:
            vals = [c["consistency"] for (v, p), c in consistency.items() if v == vid]
            if vals:
                lines.append(f"| {vid} | {fmt(mean(vals))} | {fmt(stdev(vals), 1)} |")

        lines.append("")
    else:
        lines.append("*No consistency data available.*")
        lines.append("")

    # 6. Variance analysis
    lines.append("## Variance Analysis")
    lines.append("")
    lines.append("Standard deviation of mean scores across all (PR, repeat) combinations per variant.")
    lines.append("")
    lines.append("| Variant | Mean | Std Dev | Min | Max | Range |")
    lines.append("|---------|------|---------|-----|-----|-------|")

    for vid in sorted_variants:
        vals = [s["mean_score"] for (v, p, r), s in scores.items() if v == vid]
        if vals:
            lines.append(
                f"| {vid} | {fmt(mean(vals))} | {fmt(stdev(vals))} | "
                f"{fmt(min(vals))} | {fmt(max(vals))} | {fmt(max(vals) - min(vals))} |"
            )

    lines.append("")

    # 7. Timing analysis
    lines.append("## Timing Analysis")
    lines.append("")
    lines.append("| Variant | Mean Duration (s) | Min (s) | Max (s) |")
    lines.append("|---------|------------------|---------|---------|")

    for vid in sorted_variants:
        durations = [
            r["duration_ms"] / 1000
            for (v, p, run), r in results.items()
            if v == vid and not r.get("error")
        ]
        if durations:
            lines.append(
                f"| {vid} | {fmt(mean(durations), 1)} | "
                f"{fmt(min(durations), 1)} | {fmt(max(durations), 1)} |"
            )

    lines.append("")

    # 8. Manual review index
    lines.append("## Manual Review Index")
    lines.append("")
    lines.append("For each (variant, PR), the best and worst repeat as identified by the consistency judge.")
    lines.append("")
    lines.append("| Variant | PR | Best Run | Worst Run | Best File | Worst File |")
    lines.append("|---------|-----|----------|-----------|-----------|------------|")

    run_label_to_num = {"A": 1, "B": 2, "C": 3}
    for vid in sorted_variants:
        for pr_info in TEST_PRS:
            pr_num = pr_info["number"]
            key = (vid, pr_num)
            if key not in consistency:
                continue
            c = consistency[key]

            best_num = run_label_to_num.get(c["best_run"], 1)
            worst_num = run_label_to_num.get(c["worst_run"], 1)

            best_file = f"results/{vid}/pr_{pr_num}_run{best_num}.json"
            worst_file = f"results/{vid}/pr_{pr_num}_run{worst_num}.json"

            lines.append(
                f"| {vid} | #{pr_num} | Run {best_num} | Run {worst_num} | "
                f"`{best_file}` | `{worst_file}` |"
            )

    lines.append("")

    # 9. Judge score summaries
    lines.append("## Score Distribution")
    lines.append("")
    lines.append("Per-criterion distribution across all reviews.")
    lines.append("")
    lines.append("| Criterion | Mean | Std | Min | Max |")
    lines.append("|-----------|------|-----|-----|-----|")

    for c in CRITERIA:
        vals = [s[c] for s in scores.values()]
        if vals:
            lines.append(
                f"| {CRITERIA_SHORT[c]} | {fmt(mean(vals))} | {fmt(stdev(vals))} | "
                f"{min(vals)} | {max(vals)} |"
            )

    lines.append("")

    # 10. Individual justifications (abbreviated)
    lines.append("## Notable Judge Justifications")
    lines.append("")

    # Show the top 5 and bottom 5 reviews by mean score
    all_scored = sorted(scores.items(), key=lambda x: x[1]["mean_score"], reverse=True)

    lines.append("### Top 5 Reviews")
    lines.append("")
    for (vid, pr, run), s in all_scored[:5]:
        lines.append(f"- **{vid}** PR #{pr} run {run} (mean {fmt(s['mean_score'])}): {s.get('brief_justification', 'N/A')}")

    lines.append("")
    lines.append("### Bottom 5 Reviews")
    lines.append("")
    for (vid, pr, run), s in all_scored[-5:]:
        lines.append(f"- **{vid}** PR #{pr} run {run} (mean {fmt(s['mean_score'])}): {s.get('brief_justification', 'N/A')}")

    lines.append("")

    return "\n".join(lines)


@click.command()
@click.option("--output", default=None, type=click.Path(), help="Output file (default: report/summary.md)")
def main(output: str):
    """Generate the benchmark analysis report from scored reviews."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = Path(output) if output else REPORT_DIR / "summary.md"

    logger.info("Loading scores...")
    scores = load_all_scores()
    logger.info(f"Loaded {len(scores)} individual scores")

    consistency = load_all_consistency()
    logger.info(f"Loaded {len(consistency)} consistency scores")

    results = load_all_results()
    logger.info(f"Loaded {len(results)} raw results")

    if not scores:
        logger.error("No scores found. Run judge.py first.")
        return

    logger.info("Generating report...")
    report = generate_report(scores, consistency, results)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)
    logger.info(f"Report saved to: {output_path}")

    # Also print summary stats to console
    variant_means = defaultdict(list)
    for (vid, pr, run), s in scores.items():
        variant_means[vid].append(s["mean_score"])

    click.echo("\n=== Quick Summary ===\n")
    sorted_vids = sorted(variant_means.keys(), key=lambda v: mean(variant_means[v]), reverse=True)
    for vid in sorted_vids:
        vals = variant_means[vid]
        click.echo(f"  {vid:20s}  mean={fmt(mean(vals))}  std={fmt(stdev(vals))}  n={len(vals)}")


if __name__ == "__main__":
    main()
