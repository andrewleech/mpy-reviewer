#!/usr/bin/env python3
"""
Sample random open issues from a repo, clone them to a fork, run triage, and generate a report.

This script:
1. Searches for N random open issues in the source repo
2. Clones each to the target fork via gh issue create
3. Runs triage_issue on each cloned issue
4. Collects results into a markdown report at test_results/triage_report.md
"""

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from collect_utils import gh_api, REQUEST_DELAY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def search_open_issues(repo, limit=100):
    """Search for all open issues in repo, respecting GitHub's 1000 result limit."""
    query = f"repo:{repo} is:issue -is:pr is:open"
    items = []
    page = 1
    per_page = 100

    while len(items) < limit:
        endpoint = f"search/issues?q={query}&per_page={per_page}&page={page}&sort=updated&order=desc"
        result = gh_api(endpoint)

        if result is None or "items" not in result:
            break

        result_items = result["items"]
        if not result_items:
            break

        items.extend(result_items)

        if len(result_items) < per_page:
            break

        if page >= 10:
            total_count = result.get("total_count", 0)
            if total_count > 1000:
                logger.warning(f"Found {total_count} results but only 1000 accessible")
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    return items[:limit]


def clone_issue_to_fork(source_repo, source_number, target_repo, source_title, source_body):
    """Create a test issue in the fork repo."""
    title = f"[TRIAGE TEST #{source_number}] {source_title}"
    body = source_body + f"\n\n---\nCloned from {source_repo}#{source_number} for triage testing."

    cmd = [
        "gh", "issue", "create",
        "-R", target_repo,
        "-t", title,
        "-b", body,
    ]

    import subprocess
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"Failed to clone issue #{source_number}: {result.stderr}")
        return None

    # Parse issue number from output (typically "https://github.com/owner/repo/issues/123")
    output = result.stdout.strip()
    if output:
        parts = output.split("/")
        try:
            return int(parts[-1])
        except (ValueError, IndexError):
            logger.error(f"Could not parse issue number from: {output}")
            return None

    return None


def fetch_issue_details(repo, issue_number):
    """Fetch full issue details from GitHub."""
    endpoint = f"repos/{repo}/issues/{issue_number}"
    return gh_api(endpoint)


def run_triage_on_issue(repo, issue_number):
    """Run triage on a cloned issue and collect results."""
    try:
        issue = fetch_issue_details(repo, issue_number)
        if not issue:
            logger.error(f"Could not fetch issue #{issue_number}")
            return None

        time.sleep(REQUEST_DELAY)

        # Import triage modules
        from triage.retriever import IssueRetriever
        from triage.prompt_builder import TriageContext, get_triage_builder
        from triage.confidence import compute_duplicate_confidence

        title = issue.get("title", "")
        body = issue.get("body", "") or ""
        state = issue.get("state", "open")
        labels = [l["name"] for l in issue.get("labels", [])]

        # Initialize retriever
        retriever = IssueRetriever()

        # Search for similar issues
        similar_issues = retriever.search_similar_issues(
            f"{title} {body}",
            top_k=10,
            state="open"
        )

        # Find potential duplicates
        duplicates = retriever.find_potential_duplicates(
            title,
            body,
            top_k=5
        )

        # Search for related reviews
        related_reviews = retriever.find_related_reviews(
            f"{title} {body}",
            top_k=5
        )

        # Check for closing references
        closing_refs = retriever.check_closing_refs(issue_number, repo)

        # Build triage context
        context = TriageContext(
            issue_number=issue_number,
            issue_title=title,
            issue_body=body,
            issue_labels=labels,
            issue_state=state,
            issue_repo=repo,
            similar_issues=similar_issues,
            related_reviews=related_reviews,
            closing_refs=closing_refs,
            codebase_context=None,
        )

        # Get prompt builder
        builder = get_triage_builder()
        prompt = builder.build_triage_prompt(context)

        # Extract suggested labels and duplicates for report
        suggested_labels = []
        duplicate_info = None

        if duplicates:
            top_dup = duplicates[0]
            similarity = top_dup.get("rrf_score", 0.0)
            has_merged = False
            for ref in closing_refs:
                if ref.get("pr_merged"):
                    has_merged = True
                    break

            title_overlap = 0.0
            dup_confidence = compute_duplicate_confidence(
                similarity,
                has_merged,
                title_overlap
            )

            if dup_confidence >= 0.5:
                dup_num = top_dup.get("issue_number", "?")
                duplicate_info = {
                    "issue_number": dup_num,
                    "confidence": dup_confidence,
                    "evidence": f"Semantic similarity (RRF): {similarity:.2f}",
                    "has_merged_ref": has_merged,
                }

        return {
            "issue_number": issue_number,
            "original_number": int(title.split("#")[1].split("]")[0]),
            "title": title,
            "original_labels": labels,
            "suggested_labels": suggested_labels,
            "duplicate_info": duplicate_info,
            "similar_issues_count": len(similar_issues) if similar_issues else 0,
            "related_reviews_count": len(related_reviews) if related_reviews else 0,
            "closing_refs_count": len(closing_refs) if closing_refs else 0,
            "prompt_snippet": prompt[:500] + "..." if len(prompt) > 500 else prompt,
        }

    except Exception as e:
        logger.error(f"Error running triage on issue #{issue_number}: {e}", exc_info=True)
        return None


def generate_report(results, output_path):
    """Generate a markdown report from triage results."""
    report_lines = [
        "# Issue Triage Test Report",
        "",
        f"Generated: {datetime.now().isoformat()}",
        "",
        f"**Issues tested:** {len(results)}",
        "",
    ]

    for result in results:
        if result is None:
            continue

        report_lines.extend([
            f"## Issue #{result['issue_number']} (cloned from #{result['original_number']})",
            "",
            f"**Title:** {result['title']}",
            "",
            f"**Original Labels:** {', '.join(result['original_labels']) if result['original_labels'] else '(none)'}",
            "",
            f"**Suggested Labels:** {', '.join(result['suggested_labels']) if result['suggested_labels'] else '(none)'}",
            "",
        ])

        if result.get("duplicate_info"):
            dup = result["duplicate_info"]
            report_lines.extend([
                f"**Duplicate Detection:**",
                f"- Potential duplicate: #{dup['issue_number']}",
                f"- Confidence: {dup['confidence']:.2f}",
                f"- Evidence: {dup['evidence']}",
                f"- Has merged closing ref: {dup['has_merged_ref']}",
                "",
            ])

        report_lines.extend([
            f"**Similar Issues Found:** {result['similar_issues_count']}",
            "",
            f"**Related Reviews Found:** {result['related_reviews_count']}",
            "",
            f"**Closing References Found:** {result['closing_refs_count']}",
            "",
            "---",
            "",
        ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(report_lines))

    logger.info(f"Report written to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Sample issues from source repo, clone to fork, run triage, generate report."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of issues to sample (default: 10)",
    )
    parser.add_argument(
        "--repo",
        default="micropython/micropython",
        help="Source repository (default: micropython/micropython)",
    )
    parser.add_argument(
        "--fork",
        default="andrewleech/micropython",
        help="Target fork repository (default: andrewleech/micropython)",
    )
    parser.add_argument(
        "--skip-clone",
        action="store_true",
        help="Skip cloning; only run triage on already-cloned issues",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without cloning",
    )
    parser.add_argument(
        "--output",
        default="test_results/triage_report.md",
        help="Output report path (default: test_results/triage_report.md)",
    )

    args = parser.parse_args()

    logger.info(f"Sampling {args.count} issues from {args.repo}")

    # Search for open issues
    logger.info(f"Searching for open issues in {args.repo}...")
    issues = search_open_issues(args.repo, limit=args.count * 3)  # Fetch extra to sample from
    if not issues:
        logger.error("No issues found")
        sys.exit(1)

    # Randomly sample
    sampled = random.sample(issues, min(args.count, len(issues)))
    logger.info(f"Sampled {len(sampled)} issues")

    cloned_numbers = []

    if not args.skip_clone:
        # Clone issues to fork
        logger.info(f"Cloning to {args.fork}...")
        for issue in sampled:
            issue_num = issue["number"]
            title = issue.get("title", "")
            body = issue.get("body", "") or ""

            if args.dry_run:
                logger.info(f"[DRY RUN] Would clone #{issue_num}: {title}")
                cloned_numbers.append(issue_num)  # Dummy; won't actually run triage
                continue

            logger.info(f"Cloning issue #{issue_num}...")
            cloned_num = clone_issue_to_fork(
                args.repo,
                issue_num,
                args.fork,
                title,
                body
            )

            if cloned_num:
                logger.info(f"Cloned to #{cloned_num}")
                cloned_numbers.append(cloned_num)
                time.sleep(REQUEST_DELAY)
            else:
                logger.warning(f"Failed to clone issue #{issue_num}")

    if args.dry_run:
        logger.info("[DRY RUN] Would run triage on cloned issues")
        logger.info("[DRY RUN] Skipping report generation")
        return

    # Run triage on cloned issues
    logger.info(f"Running triage on {len(cloned_numbers)} cloned issues...")
    results = []
    for cloned_num in cloned_numbers:
        logger.info(f"Triaging #{cloned_num}...")
        result = run_triage_on_issue(args.fork, cloned_num)
        if result:
            results.append(result)
            logger.info(f"Triage completed for #{cloned_num}")
        else:
            logger.warning(f"Triage failed for #{cloned_num}")

    # Generate report
    output_path = Path(args.output)
    generate_report(results, output_path)
    logger.info(f"Test complete. Report: {output_path}")


if __name__ == "__main__":
    main()
