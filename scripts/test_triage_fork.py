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
from urllib.parse import quote

from collect_utils import gh_api, REQUEST_DELAY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def search_open_issues(repo, limit=100):
    """Search for all open issues in repo, respecting GitHub's 1000 result limit."""
    query = quote(f"repo:{repo} is:issue -is:pr is:open")
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


def _defuse_github_refs(text):
    """Break GitHub cross-reference patterns so they don't ping original issues.

    Replaces owner/repo#NNN and bare #NNN with non-linking equivalents.
    """
    import re
    ZWS = '\u200B'  # zero-width space breaks GitHub auto-linking
    # owner/repo#123 → owner/repo[ZWS]#123
    text = re.sub(r'(\w+/\w+)#(\d+)', rf'\1{ZWS}#\2', text)
    # Bare #123 at word boundary → #[ZWS]123
    text = re.sub(r'(?<!\w)#(\d+)\b', rf'#{ZWS}\1', text)
    return text


def clone_issue_to_fork(source_repo, source_number, target_repo, source_title, source_body):
    """Create a test issue in the fork repo."""
    title = f"[TRIAGE TEST {source_number}] {source_title}"
    safe_body = _defuse_github_refs(source_body)
    body = safe_body + f"\n\n---\nCloned from `{source_repo}` issue {source_number} for triage testing."

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

        # Filter self-matches (the source issue appears in the index)
        # Parse original issue number from "[TRIAGE TEST NNN] ..." title
        import re
        m = re.search(r'\[TRIAGE TEST #?(\d+)\]', title)
        original_number = int(m.group(1)) if m else 0
        # Strip the "[TRIAGE TEST #NNN] " prefix for title overlap calculation
        original_title_clean = title.split("] ", 1)[1] if "] " in title else title
        if similar_issues:
            similar_issues = [s for s in similar_issues if s.get("issue_number") != original_number]
        if duplicates:
            duplicates = [d for d in duplicates if d.get("issue_number") != original_number]

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

        # Extract duplicate candidates with confidence scores
        duplicate_candidates = []
        if duplicates:
            has_merged = any(ref.get("pr_merged") for ref in (closing_refs or []))
            for dup in duplicates[:3]:
                rrf = dup.get("rrf_score", 0.0)
                candidate_title = dup.get("title", "")
                title_words_query = set(original_title_clean.lower().split())
                title_words_cand = set(candidate_title.lower().split())
                overlap = (
                    len(title_words_query & title_words_cand) /
                    len(title_words_query | title_words_cand)
                    if title_words_query | title_words_cand else 0.0
                )
                confidence = compute_duplicate_confidence(rrf, has_merged, overlap)
                duplicate_candidates.append({
                    "issue_number": dup.get("issue_number", "?"),
                    "title": candidate_title,
                    "state": dup.get("state", "?"),
                    "rrf_score": rrf,
                    "confidence": confidence,
                })

        # Extract top similar issues for the report
        top_similar = []
        if similar_issues:
            for sim in similar_issues[:5]:
                top_similar.append({
                    "issue_number": sim.get("issue_number", "?"),
                    "title": sim.get("title", "(unknown)"),
                    "state": sim.get("state", "?"),
                    "rrf_score": sim.get("rrf_score", 0.0),
                })

        # Extract top related reviews
        top_reviews = []
        if related_reviews:
            for rev in related_reviews[:3]:
                top_reviews.append({
                    "pr_number": rev.get("pr_number", "?"),
                    "body": (rev.get("body", "") or "")[:150],
                    "domain": rev.get("domain", "?"),
                })

        return {
            "issue_number": issue_number,
            "original_number": original_number,
            "title": title,
            "original_labels": labels,
            "duplicate_candidates": duplicate_candidates,
            "top_similar": top_similar,
            "top_reviews": top_reviews,
            "similar_issues_count": len(similar_issues) if similar_issues else 0,
            "related_reviews_count": len(related_reviews) if related_reviews else 0,
            "closing_refs_count": len(closing_refs) if closing_refs else 0,
            "prompt_length": len(prompt),
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
            f"**Prompt length:** {result.get('prompt_length', 0):,} chars",
            "",
        ])

        # Top similar issues
        top_similar = result.get("top_similar", [])
        if top_similar:
            report_lines.extend([
                f"### Similar Issues ({result['similar_issues_count']} total)",
                "",
                "| # | Title | State | RRF Score |",
                "|---|-------|-------|-----------|",
            ])
            for sim in top_similar:
                report_lines.append(
                    f"| {sim['issue_number']} | {sim['title'][:80]} | {sim['state']} | {sim['rrf_score']:.4f} |"
                )
            report_lines.append("")

        # Duplicate candidates
        dup_candidates = result.get("duplicate_candidates", [])
        if dup_candidates:
            report_lines.extend([
                "### Duplicate Candidates",
                "",
                "| # | Title | State | RRF Score | Confidence |",
                "|---|-------|-------|-----------|------------|",
            ])
            for dup in dup_candidates:
                report_lines.append(
                    f"| {dup['issue_number']} | {dup['title'][:80]} | {dup['state']} | {dup['rrf_score']:.4f} | {dup['confidence']:.2f} |"
                )
            report_lines.append("")

        # Related reviews
        top_reviews = result.get("top_reviews", [])
        if top_reviews:
            report_lines.extend([
                f"### Related Reviews ({result['related_reviews_count']} total)",
                "",
            ])
            for rev in top_reviews:
                body_preview = rev['body'].replace('\n', ' ').strip()
                report_lines.extend([
                    f"- **PR #{rev['pr_number']}** ({rev['domain']}): {body_preview}",
                ])
            report_lines.append("")

        report_lines.extend([
            f"**Closing References:** {result['closing_refs_count']}",
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
        "--issues",
        type=str,
        default="",
        help="Comma-separated issue numbers to triage (use with --skip-clone)",
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

    cloned_numbers = []

    if args.issues:
        cloned_numbers = [int(n.strip()) for n in args.issues.split(",") if n.strip()]
        logger.info(f"Using provided issue numbers: {cloned_numbers}")
    else:
        logger.info(f"Sampling {args.count} issues from {args.repo}")

        # Search for open issues
        logger.info(f"Searching for open issues in {args.repo}...")
        issues = search_open_issues(args.repo, limit=args.count * 3)
        if not issues:
            logger.error("No issues found")
            sys.exit(1)

        # Randomly sample
        sampled = random.sample(issues, min(args.count, len(issues)))
        logger.info(f"Sampled {len(sampled)} issues")

    if not cloned_numbers and not args.skip_clone:
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
