#!/usr/bin/env python3
"""Analyze usage logs for performance insights."""

import json
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime


def load_logs(log_file: Path):
    """Load all log entries from JSONL file."""
    if not log_file.exists():
        return []

    logs = []
    with open(log_file) as f:
        for line in f:
            if line.strip():
                logs.append(json.loads(line))
    return logs


def analyze_performance(logs):
    """Analyze performance metrics from logs."""
    if not logs:
        print("No usage logs found.")
        return

    # Group by operation
    by_operation = defaultdict(list)
    for log in logs:
        by_operation[log["operation"]].append(log)

    print("=== Performance Analysis ===\n")

    # Overall stats
    total_operations = len(logs)
    total_errors = sum(1 for log in logs if log.get("error"))
    print(f"Total operations: {total_operations}")
    print(f"Total errors: {total_errors}")
    print(f"Success rate: {100 * (1 - total_errors / total_operations):.1f}%\n")

    # Per-operation stats
    for operation, op_logs in sorted(by_operation.items()):
        print(f"\n{operation}:")
        print(f"  Count: {len(op_logs)}")

        durations = [log["duration_ms"] for log in op_logs if not log.get("error")]
        if durations:
            print(f"  Avg duration: {sum(durations) / len(durations):.0f} ms")
            print(f"  Min duration: {min(durations):.0f} ms")
            print(f"  Max duration: {max(durations):.0f} ms")

        results = [log["result_count"] for log in op_logs if not log.get("error")]
        if results:
            print(f"  Avg results: {sum(results) / len(results):.1f}")

        errors = [log for log in op_logs if log.get("error")]
        if errors:
            print(f"  Errors: {len(errors)}")
            print(f"  Error types:")
            error_types = defaultdict(int)
            for log in errors:
                error_types[log["error"][:50]] += 1
            for error, count in sorted(error_types.items(), key=lambda x: -x[1])[:3]:
                print(f"    - {error}... ({count}x)")

    # Parameter analysis for review operations
    review_logs = by_operation.get("review", [])
    if review_logs:
        print("\n\nReview Operation Analysis:")

        # Analyze impact of flags
        with_rerank = [log for log in review_logs if log["params"].get("rerank")]
        without_rerank = [log for log in review_logs if not log["params"].get("rerank")]

        if with_rerank and without_rerank:
            avg_with = sum(log["duration_ms"] for log in with_rerank) / len(with_rerank)
            avg_without = sum(log["duration_ms"] for log in without_rerank) / len(without_rerank)
            print(f"  With --rerank: {avg_with:.0f} ms (n={len(with_rerank)})")
            print(f"  Without --rerank: {avg_without:.0f} ms (n={len(without_rerank)})")
            print(f"  Rerank overhead: +{avg_with - avg_without:.0f} ms ({100 * (avg_with / avg_without - 1):.0f}%)")

        with_codebase = [log for log in review_logs if log["params"].get("codebase")]
        without_codebase = [log for log in review_logs if not log["params"].get("codebase")]

        if with_codebase and without_codebase:
            avg_with = sum(log["duration_ms"] for log in with_codebase) / len(with_codebase)
            avg_without = sum(log["duration_ms"] for log in without_codebase) / len(without_codebase)
            print(f"\n  With --codebase: {avg_with:.0f} ms (n={len(with_codebase)})")
            print(f"  Without --codebase: {avg_without:.0f} ms (n={len(without_codebase)})")
            print(f"  Codebase overhead: +{avg_with - avg_without:.0f} ms ({100 * (avg_with / avg_without - 1):.0f}%)")

    # Recent activity
    print("\n\n=== Recent Activity (last 10) ===\n")
    for log in logs[-10:]:
        timestamp = datetime.fromisoformat(log["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        operation = log["operation"]
        duration = log["duration_ms"]
        results = log["result_count"]
        error = " [ERROR]" if log.get("error") else ""
        print(f"{timestamp} | {operation:20s} | {duration:6.0f} ms | {results:3d} results{error}")


def main():
    """Entry point."""
    log_file = Path(__file__).parent.parent / "logs" / "usage.jsonl"

    if not log_file.exists():
        print(f"No usage log found at {log_file}")
        print("Usage logging is enabled - logs will be created as you use the CLI.")
        sys.exit(0)

    logs = load_logs(log_file)
    analyze_performance(logs)


if __name__ == "__main__":
    main()
