#!/usr/bin/env python3
"""
Query the MicroPython review database for guidance and analysis.

Provides CLI commands to search, filter, and extract insights from
aggregated review comments and themes.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"


class ReviewDB:
    """Interface to the review database."""

    def __init__(self, db_path: str = None):
        """Initialize database connection."""
        if db_path is None:
            db_path = str(DB_PATH)

        if not Path(db_path).exists():
            print(f"Error: Database not found at {db_path}", file=sys.stderr)
            sys.exit(1)

        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        """Close database connection."""
        self.conn.close()

    def path_to_component(self, path: str) -> str:
        """Map file path to component domain mapping.

        Examples:
            ports/stm32/something.c -> stm32
            py/obj.c -> core
            extmod/machine_uart.c -> extmod
            esp32/main.c -> esp32
        """
        parts = path.split("/")
        if not parts:
            return "unknown"

        first = parts[0]

        # Map first-level directories to components
        port_map = {
            "ports": parts[1] if len(parts) > 1 else "unknown",
            "py": "core",
            "extmod": "extmod",
            "lib": "lib",
            "tests": "tests",
            "tools": "tools",
            "docs": "docs",
            "mpy-cross": "mpy-cross",
        }

        return port_map.get(first, first)

    def get_domain_id(self, domain_name: Optional[str]) -> Optional[int]:
        """Get domain ID by name, or None if not specified."""
        if domain_name is None:
            return None

        cursor = self.conn.cursor()
        cursor.execute("SELECT id FROM domains WHERE name = ?", (domain_name,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_domain_name(self, domain_id: int) -> str:
        """Get domain name by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM domains WHERE id = ?", (domain_id,))
        row = cursor.fetchone()
        return row[0] if row else f"domain_{domain_id}"

    def guidance_for_files(self, file_paths: list, domain: Optional[str] = None,
                          change_type: Optional[str] = None) -> dict:
        """Get guidance for reviewing specific files.

        Returns relevant themes and example comments.
        """
        components = [self.path_to_component(fp) for fp in file_paths]

        query = """
            SELECT DISTINCT
                cc.theme, d.name as domain, d.id as domain_id,
                COUNT(cc.id) as comment_count
            FROM comment_categories cc
            JOIN domains d ON cc.domain_id = d.id
            WHERE cc.theme IS NOT NULL
        """
        params = []

        if domain:
            domain_id = self.get_domain_id(domain)
            if domain_id is not None:
                query += " AND d.id = ?"
                params.append(domain_id)

        query += " GROUP BY cc.theme ORDER BY comment_count DESC"

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        themes = cursor.fetchall()

        # Get example comments for each theme
        examples = []
        for theme in themes:
            ex_query = """
                SELECT DISTINCT
                    CASE
                        WHEN cc.comment_type = 'review_comment' THEN rc.body
                        WHEN cc.comment_type = 'issue_comment' THEN ic.body
                        WHEN cc.comment_type = 'review' THEN r.body
                        ELSE NULL
                    END as body,
                    cc.comment_type,
                    cc.severity,
                    rc.path
                FROM comment_categories cc
                LEFT JOIN review_comments rc ON
                    cc.comment_type = 'review_comment' AND cc.comment_id = rc.id
                LEFT JOIN issue_comments ic ON
                    cc.comment_type = 'issue_comment' AND cc.comment_id = ic.id
                LEFT JOIN reviews r ON
                    cc.comment_type = 'review' AND cc.comment_id = r.id
                WHERE cc.theme = ? AND body IS NOT NULL
                LIMIT 3
            """
            cursor.execute(ex_query, (theme["theme"],))
            theme_examples = cursor.fetchall()

            for ex in theme_examples:
                if ex["body"]:  # Ensure we have actual body content
                    examples.append({
                        "theme": theme["theme"],
                        "domain": theme["domain"],
                        "comment": ex["body"][:500],  # Truncate long comments
                        "type": ex["comment_type"],
                        "severity": ex["severity"]
                    })

        # Style tips (comments marked as style examples)
        style_query = """
            SELECT DISTINCT
                CASE
                    WHEN cc.comment_type = 'review_comment' THEN rc.body
                    WHEN cc.comment_type = 'issue_comment' THEN ic.body
                    WHEN cc.comment_type = 'review' THEN r.body
                    ELSE NULL
                END as body,
                cc.theme,
                d.name as domain
            FROM comment_categories cc
            JOIN domains d ON cc.domain_id = d.id
            LEFT JOIN review_comments rc ON
                cc.comment_type = 'review_comment' AND cc.comment_id = rc.id
            LEFT JOIN issue_comments ic ON
                cc.comment_type = 'issue_comment' AND cc.comment_id = ic.id
            LEFT JOIN reviews r ON
                cc.comment_type = 'review' AND cc.comment_id = r.id
            WHERE cc.is_style_example = 1
        """
        if domain:
            domain_id = self.get_domain_id(domain)
            if domain_id is not None:
                style_query += " AND d.id = ?"
                cursor.execute(style_query, (domain_id,))
            else:
                cursor.execute(style_query)
        else:
            cursor.execute(style_query)

        style_tips = [
            row["body"][:300]
            for row in cursor.fetchall()
            if row["body"]
        ]

        return {
            "files_analyzed": file_paths,
            "components": components,
            "relevant_themes": [
                {
                    "name": t["theme"],
                    "domain": t["domain"],
                    "comment_count": t["comment_count"]
                }
                for t in themes[:10]
            ],
            "example_comments": examples[:15],
            "style_tips": style_tips[:5]
        }

    def search_comments(self, pattern: str, domain: Optional[str] = None) -> dict:
        """Full-text search through comment bodies."""
        query = """
            SELECT
                CASE
                    WHEN cc.comment_type = 'review_comment' THEN rc.body
                    WHEN cc.comment_type = 'issue_comment' THEN ic.body
                    WHEN cc.comment_type = 'review' THEN r.body
                    ELSE NULL
                END as body,
                cc.comment_type,
                COALESCE(rc.path, 'N/A') as file_path,
                d.name as domain,
                cc.theme,
                cc.severity
            FROM comment_categories cc
            LEFT JOIN review_comments rc ON
                cc.comment_type = 'review_comment' AND cc.comment_id = rc.id
            LEFT JOIN issue_comments ic ON
                cc.comment_type = 'issue_comment' AND cc.comment_id = ic.id
            LEFT JOIN reviews r ON
                cc.comment_type = 'review' AND cc.comment_id = r.id
            LEFT JOIN domains d ON cc.domain_id = d.id
            WHERE 1=1
        """
        params = []

        # Add search pattern (case-insensitive)
        query += " AND (rc.body LIKE ? OR ic.body LIKE ? OR r.body LIKE ?)"
        search_pattern = f"%{pattern}%"
        params.extend([search_pattern, search_pattern, search_pattern])

        if domain:
            domain_id = self.get_domain_id(domain)
            if domain_id is not None:
                query += " AND d.id = ?"
                params.append(domain_id)

        query += " LIMIT 50"

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

        results = []
        for row in rows:
            if row["body"]:
                results.append({
                    "body": row["body"],
                    "type": row["comment_type"],
                    "file": row["file_path"],
                    "domain": row["domain"],
                    "theme": row["theme"] or "uncategorized",
                    "severity": row["severity"]
                })

        return {
            "pattern": pattern,
            "domain_filter": domain,
            "total_matches": len(results),
            "results": results
        }

    def get_stats(self) -> dict:
        """Get database statistics."""
        cursor = self.conn.cursor()

        # Total counts
        cursor.execute("SELECT COUNT(*) FROM prs")
        pr_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM review_comments")
        review_comment_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM issue_comments")
        issue_comment_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reviews")
        review_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM comment_categories")
        categorized_count = cursor.fetchone()[0]

        # Comments by domain
        cursor.execute("""
            SELECT d.name, COUNT(cc.id) as count
            FROM domains d
            LEFT JOIN comment_categories cc ON d.id = cc.domain_id
            GROUP BY d.id
            ORDER BY count DESC
        """)
        by_domain = {}
        for row in cursor.fetchall():
            by_domain[row["name"]] = row["count"]

        # Comments by type
        cursor.execute("""
            SELECT comment_type, COUNT(*) as count
            FROM comment_categories
            GROUP BY comment_type
            ORDER BY count DESC
        """)
        by_type = {row["comment_type"]: row["count"] for row in cursor.fetchall()}

        # Comments by severity
        cursor.execute("""
            SELECT severity, COUNT(*) as count
            FROM comment_categories
            WHERE severity IS NOT NULL
            GROUP BY severity
            ORDER BY count DESC
        """)
        by_severity = {row["severity"]: row["count"] for row in cursor.fetchall()}

        return {
            "total_prs": pr_count,
            "total_review_comments": review_comment_count,
            "total_issue_comments": issue_comment_count,
            "total_reviews": review_count,
            "total_categorized_comments": categorized_count,
            "comments_by_domain": by_domain,
            "comments_by_type": by_type,
            "comments_by_severity": by_severity
        }

    def get_examples(self, domain: str, limit: int = 10) -> dict:
        """Get example comments for a specific domain."""
        domain_id = self.get_domain_id(domain)
        if domain_id is None:
            return {
                "error": f"Domain '{domain}' not found",
                "valid_domains": self.list_domains()
            }

        query = """
            SELECT
                CASE
                    WHEN cc.comment_type = 'review_comment' THEN rc.body
                    WHEN cc.comment_type = 'issue_comment' THEN ic.body
                    WHEN cc.comment_type = 'review' THEN r.body
                    ELSE NULL
                END as body,
                cc.theme,
                cc.severity,
                cc.comment_type,
                cc.is_style_example,
                COALESCE(rc.path, 'N/A') as file_path
            FROM comment_categories cc
            LEFT JOIN review_comments rc ON
                cc.comment_type = 'review_comment' AND cc.comment_id = rc.id
            LEFT JOIN issue_comments ic ON
                cc.comment_type = 'issue_comment' AND cc.comment_id = ic.id
            LEFT JOIN reviews r ON
                cc.comment_type = 'review' AND cc.comment_id = r.id
            WHERE cc.domain_id = ?
            ORDER BY cc.is_style_example DESC, cc.severity IS NOT NULL DESC
            LIMIT ?
        """

        cursor = self.conn.cursor()
        cursor.execute(query, (domain_id, limit))
        rows = cursor.fetchall()

        examples = []
        for row in rows:
            if row["body"]:
                examples.append({
                    "body": row["body"],
                    "theme": row["theme"] or "uncategorized",
                    "severity": row["severity"],
                    "type": row["comment_type"],
                    "is_style_example": bool(row["is_style_example"]),
                    "file": row["file_path"]
                })

        return {
            "domain": domain,
            "total_available": len(examples),
            "examples": examples
        }

    def list_themes(self, domain: Optional[str] = None) -> dict:
        """List all themes, optionally filtered by domain."""
        query = """
            SELECT DISTINCT
                cc.theme, d.name as domain,
                COUNT(cc.id) as comment_count
            FROM comment_categories cc
            JOIN domains d ON cc.domain_id = d.id
            WHERE cc.theme IS NOT NULL
        """
        params = []

        if domain:
            domain_id = self.get_domain_id(domain)
            if domain_id is not None:
                query += " AND d.id = ?"
                params.append(domain_id)
            else:
                return {
                    "error": f"Domain '{domain}' not found",
                    "valid_domains": self.list_domains()
                }

        query += " GROUP BY cc.theme ORDER BY d.name, cc.theme"

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

        themes_by_domain = {}
        for row in rows:
            domain_name = row["domain"]
            if domain_name not in themes_by_domain:
                themes_by_domain[domain_name] = []

            themes_by_domain[domain_name].append({
                "name": row["theme"],
                "comment_count": row["comment_count"]
            })

        return {
            "domain_filter": domain,
            "themes": themes_by_domain
        }

    def list_domains(self) -> list:
        """List all available domains."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name, description FROM domains ORDER BY name")
        return [
            {"name": row["name"], "description": row["description"]}
            for row in cursor.fetchall()
        ]


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Query MicroPython review database for guidance and analysis"
    )

    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help=f"Path to database (default: {DB_PATH})"
    )

    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output"
    )

    subparsers = parser.add_subparsers(dest="command", help="Query command")

    # guidance command
    guidance_parser = subparsers.add_parser(
        "guidance",
        help="Get review guidance for specific files"
    )
    guidance_parser.add_argument(
        "--files",
        nargs="+",
        required=True,
        help="File paths to get guidance for"
    )
    guidance_parser.add_argument(
        "--domain",
        type=str,
        help="Filter by domain (e.g., memory, code_style)"
    )
    guidance_parser.add_argument(
        "--change-type",
        type=str,
        help="Type of change (feature, bugfix, etc.)"
    )

    # search command
    search_parser = subparsers.add_parser(
        "search",
        help="Full-text search through comments"
    )
    search_parser.add_argument(
        "--pattern",
        required=True,
        help="Search pattern (case-insensitive)"
    )
    search_parser.add_argument(
        "--domain",
        type=str,
        help="Filter by domain"
    )

    # stats command
    stats_parser = subparsers.add_parser(
        "stats",
        help="Show database statistics"
    )

    # examples command
    examples_parser = subparsers.add_parser(
        "examples",
        help="Get example comments for a domain"
    )
    examples_parser.add_argument(
        "--domain",
        required=True,
        help="Domain to get examples for"
    )
    examples_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of examples (default: 10)"
    )

    # themes command
    themes_parser = subparsers.add_parser(
        "themes",
        help="List all themes"
    )
    themes_parser.add_argument(
        "--domain",
        type=str,
        help="Filter by domain"
    )

    # domains command
    domains_parser = subparsers.add_parser(
        "domains",
        help="List all available domains"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Connect to database
    db = ReviewDB(args.db)

    try:
        result = None

        if args.command == "guidance":
            result = db.guidance_for_files(
                args.files,
                domain=args.domain,
                change_type=args.change_type
            )

        elif args.command == "search":
            result = db.search_comments(args.pattern, domain=args.domain)

        elif args.command == "stats":
            result = db.get_stats()

        elif args.command == "examples":
            result = db.get_examples(args.domain, limit=args.limit)

        elif args.command == "themes":
            result = db.list_themes(domain=args.domain)

        elif args.command == "domains":
            result = {"domains": db.list_domains()}

        # Output result
        if result:
            if args.pretty:
                print(json.dumps(result, indent=2))
            else:
                print(json.dumps(result))

    finally:
        db.close()


if __name__ == "__main__":
    main()
