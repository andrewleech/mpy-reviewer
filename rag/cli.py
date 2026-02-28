"""Command-line interface for mpy-reviewer."""

import sys
import json
import logging
from pathlib import Path
from typing import Optional

import click

from .config import get_config, Config
from .usage_logger import get_logger
from . import __version__


def setup_logging(verbose: bool):
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


@click.group()
@click.version_option(version=__version__)
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.pass_context
def cli(ctx, verbose: bool):
    """MicroPython Review RAG - code review assistant."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    setup_logging(verbose)


@cli.command()
@click.option("--force", is_flag=True, help="Overwrite existing index")
@click.option("--batch-size", default=100, help="Batch size for embedding")
@click.pass_context
def index(ctx, force: bool, batch_size: int):
    """Build the vector index from SQLite database."""
    from .indexer import build_index, index_stats

    logger = get_logger()

    with logger.track_operation(
        "index",
        force=force,
        batch_size=batch_size,
    ) as log_ctx:
        click.echo("Building index...")

        # Show current stats
        stats = index_stats()
        if stats["exists"]:
            click.echo(f"Existing index: {stats['num_records']} records")
            if not force:
                click.echo("Use --force to overwrite")
                return

        # Build index
        count = build_index(batch_size=batch_size, force=force)
        log_ctx.set_result_count(count)
        click.echo(f"Indexed {count} records")


@cli.command()
@click.pass_context
def stats(ctx):
    """Show index statistics."""
    from .indexer import index_stats

    stats = index_stats()

    click.echo(f"Database path: {stats['db_path']}")
    click.echo(f"Index exists: {stats['exists']}")

    if stats["exists"]:
        click.echo(f"Number of records: {stats['num_records']}")

    if "error" in stats:
        click.echo(f"Error: {stats['error']}")


@cli.command()
@click.argument("query")
@click.option("-k", "--top-k", default=10, help="Number of results")
@click.option("--domain", help="Filter by domain")
@click.option("--severity", help="Filter by severity")
@click.option("--component", help="Filter by component")
@click.option("--style-only", is_flag=True, help="Only show style examples")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def search(
    ctx,
    query: str,
    top_k: int,
    domain: Optional[str],
    severity: Optional[str],
    component: Optional[str],
    style_only: bool,
    output_json: bool,
):
    """Search for similar reviews."""
    from .retriever import get_retriever

    logger = get_logger()

    with logger.track_operation(
        "search",
        query=query,
        domain=domain,
        severity=severity,
        component=component,
        style_only=style_only,
        top_k=top_k,
    ) as log_ctx:
        retriever = get_retriever()
        results = retriever.search_with_filters(
            query,
            domain=domain,
            severity=severity,
            component=component,
            is_style_example=True if style_only else None,
            top_k=top_k,
        )
        log_ctx.set_result_count(len(results))

    if output_json:
        # Clean up results for JSON output
        output = []
        for r in results:
            output.append({
                "comment_id": r["comment_id"],
                "comment_type": r["comment_type"],
                "body": r["body"],
                "domain": r.get("domain"),
                "severity": r.get("severity"),
                "score": r.get("rrf_score", 0),
            })
        click.echo(json.dumps(output, indent=2))
    else:
        # Human-readable output
        for i, result in enumerate(results, 1):
            click.echo(f"\n--- Result {i} ---")
            click.echo(f"Domain: {result.get('domain', 'N/A')} | Severity: {result.get('severity', 'N/A')}")
            click.echo(f"Score: {result.get('rrf_score', 0):.4f}")
            click.echo(f"\n{result['body'][:500]}...")
            if result.get("diff_hunk"):
                click.echo(f"\nCode context (first 200 chars):")
                click.echo(result["diff_hunk"][:200])


@cli.command()
@click.option("--pr", "pr_number", type=int, help="PR number to review")
@click.option("--repo", default="micropython/micropython", help="GitHub repository slug")
@click.option("--diff", "diff_file", type=click.Path(exists=True), help="Diff file to review")
@click.option("--stdin", "use_stdin", is_flag=True, help="Read diff from stdin")
@click.option("-k", "--top-k", default=8, help="Number of examples to retrieve")
@click.option("--rerank", is_flag=True, help="Use cross-encoder re-ranking")
@click.option("--codebase", is_flag=True, help="Include codebase context")
@click.option("--output", type=click.Choice(["context", "prompt", "json"]), default="context")
@click.pass_context
def review(
    ctx,
    pr_number: Optional[int],
    repo: str,
    diff_file: Optional[str],
    use_stdin: bool,
    top_k: int,
    rerank: bool,
    codebase: bool,
    output: str,
):
    """Generate review context for a code diff.

    Retrieves relevant past reviews and codebase context.
    """
    from .retriever import get_retriever
    from .reranker import get_reranker
    from .codebase import get_codebase_retriever
    from .prompt_builder import ReviewContext, get_builder

    logger = get_logger()

    with logger.track_operation(
        "review",
        pr_number=pr_number,
        repo=repo,
        diff_file=diff_file,
        use_stdin=use_stdin,
        top_k=top_k,
        rerank=rerank,
        codebase=codebase,
        output=output,
    ) as log_ctx:
        # Get diff content
        if pr_number:
            diff_text = _fetch_pr_diff(pr_number, repo=repo)
        elif diff_file:
            diff_text = Path(diff_file).read_text()
        elif use_stdin:
            diff_text = sys.stdin.read()
        else:
            click.echo("Error: Provide --pr, --diff, or --stdin", err=True)
            sys.exit(1)

        if not diff_text:
            click.echo("Error: Empty diff", err=True)
            sys.exit(1)

        # Extract file list from diff for file-path affinity
        from .codebase import extract_diff_file_paths
        files_changed = extract_diff_file_paths(diff_text)

        # Get similar reviews
        retriever = get_retriever()
        results = retriever.get_similar_reviews(
            diff_text, top_k=top_k * 2, diff_files=files_changed,
        )

        # Re-rank if requested
        if rerank:
            reranker = get_reranker()
            results = reranker.rerank(diff_text, results, top_k=top_k)

        # Get codebase context if requested
        codebase_context = None
        if codebase:
            codebase_retriever = get_codebase_retriever()
            codebase_context = codebase_retriever.get_context_for_diff(diff_text, top_k=5)

        log_ctx.set_result_count(len(results[:top_k]))

        if output == "json":
            output_data = {
                "review_examples": [
                    {
                        "comment_id": r["comment_id"],
                        "body": r["body"],
                        "diff_hunk": r.get("diff_hunk"),
                        "domain": r.get("domain"),
                        "severity": r.get("severity"),
                        "score": r.get("rrf_score", r.get("rerank_score", 0)),
                    }
                    for r in results[:top_k]
                ],
                "codebase_context": codebase_context,
                "query_length": len(diff_text),
            }
            click.echo(json.dumps(output_data, indent=2))

        elif output == "prompt":
            # Build full prompt with all components
            context = ReviewContext(
                diff_text=diff_text,
                review_examples=results[:top_k],
                codebase_context=codebase_context,
                pr_number=pr_number,
                files_changed=files_changed,
            )
            builder = get_builder()
            prompt = builder.build_review_prompt(context)
            click.echo(prompt)

        else:  # context
            click.echo("# Relevant Past Reviews\n")
            for i, result in enumerate(results[:top_k], 1):
                click.echo(f"## Example {i}: {result.get('domain', 'N/A')} - {result.get('severity', 'N/A')}")
                if result.get("diff_hunk"):
                    click.echo("```diff")
                    click.echo(result["diff_hunk"][:1000])
                    click.echo("```")
                click.echo(f"\nComment:\n> {result['body']}\n")
                click.echo("---\n")


def _fetch_pr_diff(pr_number: int, repo: str = "micropython/micropython") -> str:
    """Fetch diff for a PR from GitHub."""
    import subprocess

    result = subprocess.run(
        ["gh", "pr", "diff", str(pr_number), "--repo", repo],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        click.echo(f"Error fetching PR diff: {result.stderr}", err=True)
        sys.exit(1)

    return result.stdout


@cli.group()
def triage():
    """Issue triage commands."""
    pass


@triage.command("issue")
@click.argument("number", type=int)
@click.option("--repo", default="micropython/micropython", help="GitHub repository slug")
@click.option("-k", "--top-k", default=5, help="Number of similar issues")
@click.option("--codebase", is_flag=True, help="Include codebase context")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.pass_context
def triage_issue(ctx, number, repo, top_k, codebase, output_json):
    """Triage a single issue."""
    from triage.retriever import get_issue_retriever
    from triage.prompt_builder import get_triage_builder, TriageContext

    logger = get_logger()

    with logger.track_operation(
        "triage",
        issue_number=number,
        repo=repo,
        top_k=top_k,
        codebase=codebase,
    ) as log_ctx:
        retriever = get_issue_retriever()
        builder = get_triage_builder()

        # Fetch issue
        issue = retriever.get_issue(number, repo)
        if issue is None:
            click.echo(f"Issue #{number} not found in database", err=True)
            sys.exit(1)

        title = issue.get("title", "")
        body = issue.get("body", "") or ""
        state = issue.get("state", "open")
        import json as _json
        labels_raw = issue.get("labels", "[]")
        if isinstance(labels_raw, str):
            try:
                labels = _json.loads(labels_raw)
            except (_json.JSONDecodeError, TypeError):
                labels = []
        else:
            labels = labels_raw or []

        query_text = f"{title}\n\n{body}"

        # Find similar issues
        similar = retriever.find_potential_duplicates(title, body, top_k=top_k)
        similar = [s for s in similar if s.get("issue_number") != number or s.get("repo") != repo]

        # Closing refs
        closing_refs = retriever.check_closing_refs(number, repo)

        # Related reviews
        related_reviews = retriever.find_related_reviews(query_text, top_k=5)

        # Codebase context
        codebase_context = None
        if codebase:
            try:
                from rag.codebase import get_codebase_retriever
                codebase_context = get_codebase_retriever().get_context_for_diff(
                    query_text, top_k=5,
                )
            except Exception as e:
                click.echo(f"Codebase context failed: {e}", err=True)

        log_ctx.set_result_count(len(similar))

        if output_json:
            output_data = {
                "issue_number": number,
                "title": title,
                "state": state,
                "labels": labels,
                "similar_issues": [
                    {
                        "issue_number": s.get("issue_number"),
                        "title": s.get("title"),
                        "state": s.get("state"),
                        "score": s.get("rrf_score", 0),
                    }
                    for s in similar
                ],
                "closing_refs": closing_refs,
                "related_reviews_count": len(related_reviews),
            }
            click.echo(_json.dumps(output_data, indent=2))
        else:
            context = TriageContext(
                issue_number=number,
                issue_title=title,
                issue_body=body,
                issue_labels=labels,
                issue_state=state,
                issue_repo=repo,
                similar_issues=similar,
                related_reviews=related_reviews,
                closing_refs=closing_refs,
                codebase_context=codebase_context,
            )
            prompt = builder.build_triage_prompt(context)
            click.echo(prompt)


@cli.group()
def eval():
    """Evaluation commands."""
    pass


@eval.command("build-dataset")
@click.option("--output", default="eval/dataset.json", help="Output file")
@click.option("--count", default=100, help="Number of PRs to sample")
@click.option("--stratify", type=click.Choice(["domain", "severity", "component"]),
              help="Stratify by field")
def eval_build_dataset(output: str, count: int, stratify: str):
    """Build evaluation dataset from real PRs."""
    from .evaluator import DatasetBuilder
    from .config import get_config

    logger = get_logger()

    with logger.track_operation(
        "eval_build_dataset",
        output=output,
        count=count,
        stratify=stratify,
    ) as log_ctx:
        config = get_config()
        builder = DatasetBuilder(str(config.sqlite_db_path))

        click.echo(f"Building evaluation dataset with {count} samples...")
        dataset = builder.build_dataset(
            sample_size=count,
            stratify_by=stratify,
            output_path=Path(output),
        )

        log_ctx.set_result_count(len(dataset))
        click.echo(f"Built dataset with {len(dataset)} samples")
        click.echo(f"Saved to {output}")


@eval.command("retrieval")
@click.option("--dataset", required=True, help="Dataset JSON file")
@click.option("--output", default="eval/results", help="Output directory")
@click.option("--rerank", is_flag=True, help="Use re-ranking")
@click.option("--sample-limit", default=None, type=int, help="Limit samples for quick eval")
def eval_retrieval(dataset: str, output: str, rerank: bool, sample_limit: int):
    """Evaluate retrieval quality on a dataset."""
    from .evaluator import EvaluationPipeline
    from .retriever import get_retriever
    from .config import get_config

    logger = get_logger()

    with logger.track_operation(
        "eval_retrieval",
        dataset=dataset,
        output=output,
        rerank=rerank,
        sample_limit=sample_limit,
    ) as log_ctx:
        config = get_config()

        click.echo("Loading evaluation dataset...")
        with open(dataset) as f:
            samples_data = json.load(f)

        if sample_limit:
            samples_data = samples_data[:sample_limit]

        click.echo(f"Evaluating on {len(samples_data)} samples...")

        retriever = get_retriever()
        pipeline = EvaluationPipeline(str(config.sqlite_db_path))

        results = pipeline.run_evaluation(
            retriever,
            sample_size=len(samples_data),
            output_dir=Path(output),
        )

        log_ctx.set_result_count(len(samples_data))

        # Print summary
        click.echo("\n=== Evaluation Results ===\n")
        for metric, value in results["summary"].items():
            click.echo(f"{metric}: {value:.4f}")


@eval.command("metrics")
@click.option("--results-dir", required=True, help="Results directory")
def eval_metrics(results_dir: str):
    """Display evaluation metrics from results."""
    results_path = Path(results_dir) / "summary.json"

    if not results_path.exists():
        click.echo(f"Results file not found: {results_path}", err=True)
        sys.exit(1)

    with open(results_path) as f:
        metrics = json.load(f)

    click.echo("\n=== Evaluation Metrics ===\n")
    for metric, value in sorted(metrics.items()):
        click.echo(f"{metric:20s}: {value:.4f}")


def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
