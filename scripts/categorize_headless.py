#!/usr/bin/env python3
"""
Categorize dpgeorge's review comments using Claude CLI in headless mode.

Uses 'claude -p' with JSON schema to batch process comments efficiently.
Processes comments in batches of 20 for optimal context usage.
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"
BATCH_SIZE = 10  # Reduced from 20 to avoid timeouts
MAX_BUDGET = "50.00"  # $50 max spend (increased from $5)
TIMEOUT_SECONDS = 300  # Increased to 300s to allow Claude to read large files

# JSON schema for structured output
CATEGORIZATION_SCHEMA = {
    "type": "object",
    "properties": {
        "categorizations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "comment_num": {"type": "integer"},
                    "domain": {
                        "type": "string",
                        "enum": [
                            "code_style",
                            "memory",
                            "error_handling",
                            "api_design",
                            "performance",
                            "portability",
                            "documentation",
                            "testing",
                            "security",
                            "architecture",
                            "build_system",
                            "correctness",
                        ],
                    },
                    "theme": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["blocking", "suggestion", "nitpick"],
                    },
                    "is_style_example": {"type": "boolean"},
                    "component": {
                        "type": "string",
                        "enum": ["py_core", "extmod", "port_specific", "drivers", "tools",
                                 "tests", "docs", "build_system", "examples"],
                    },
                    "port": {
                        "type": ["string", "null"],
                        "enum": [None, "esp32", "stm32", "rp2", "unix", "nrf", "samd",
                                 "mimxrt", "renesas-ra", "zephyr", "webassembly", "windows"],
                    },
                    "subsystem": {
                        "type": ["string", "null"],
                        "enum": [None, "bluetooth", "networking", "usb", "filesystem", "uart",
                                 "i2c", "spi", "adc", "gpio", "pwm", "dma", "rmt", "gc", "vm",
                                 "compiler", "types", "asyncio", "ssl", "board_support"],
                    },
                    "language_context": {
                        "type": "string",
                        "enum": ["c_code", "python_code", "documentation", "makefile",
                                 "cmake", "shell_script", "yaml"],
                    },
                    "code_construct": {
                        "type": "string",
                        "enum": ["function", "macro", "struct", "typedef", "class", "module",
                                 "test_case", "documentation_page", "build_rule", "config", "include"],
                    },
                    "concern_type": {
                        "type": "string",
                        "enum": ["correctness", "safety", "api_design", "style", "performance",
                                 "portability", "maintainability", "testing", "documentation",
                                 "security", "compatibility", "architecture"],
                    },
                    "feedback_type": {
                        "type": "string",
                        "enum": ["question", "suggestion", "requirement", "information", "praise", "merge"],
                    },
                    "is_pattern": {"type": "boolean"},
                    "cpython_related": {"type": "boolean"},
                    "has_code_suggestion": {"type": "boolean"},
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 5
                    }
                },
                "required": ["comment_num", "domain", "theme", "severity", "is_style_example",
                             "component", "language_context", "code_construct", "concern_type",
                             "feedback_type", "is_pattern", "cpython_related",
                             "has_code_suggestion", "keywords"],
            },
        }
    },
    "required": ["categorizations"],
}

# Comprehensive prompt template
PROMPT_TEMPLATE = """You are analyzing code review comments from Damien George (dpgeorge), the creator and lead maintainer of MicroPython. Your task is to categorize each comment using 13 fields.

# Context
MicroPython is a lean implementation of Python 3 for microcontrollers and embedded systems. Key priorities:
- Memory efficiency (RAM/ROM constraints)
- Code correctness and reliability
- Portability across diverse hardware
- API compatibility with CPython where practical
- Performance optimization
- Maintainability and code clarity

# Categorization Guidelines

## Domain (pick the best fit):
- **code_style**: Formatting, naming, indentation, comments, code organization
- **memory**: RAM/ROM usage, memory leaks, allocation patterns, GC concerns
- **error_handling**: Exception handling, error messages, edge case handling
- **api_design**: Public interfaces, function signatures, module design, user-facing API
- **performance**: Speed optimization, algorithm efficiency, computational complexity
- **portability**: Cross-platform compatibility, hardware abstraction, OS differences
- **documentation**: Docstrings, comments, README, user documentation
- **testing**: Test coverage, test correctness, test infrastructure
- **security**: Security vulnerabilities, input validation, unsafe operations
- **architecture**: System design, module structure, abstraction layers
- **build_system**: Make, compilation, build configuration, toolchain
- **correctness**: Logic bugs, incorrect behavior, specification violations

## Theme:
Concise description of the specific issue or pattern (e.g., "unnecessary whitespace", "missing NULL check", "API should use size_t")

## Severity:
- **blocking**: Must be fixed before merge (bugs, security issues, breaking changes)
- **suggestion**: Should be fixed but not critical (improvements, optimizations, better patterns)
- **nitpick**: Minor stylistic preference (formatting, naming, minor organization)

## is_style_example:
- **true**: Comment demonstrates dpgeorge's writing style well (terse, direct, technical)
- **false**: Generic technical feedback or not particularly representative

## Component (which major area):
- **py_core**: Core Python implementation (py/*.c, py/*.h)
- **extmod**: Extended modules (extmod/*.c)
- **port_specific**: Port code (ports/*/), board configs
- **drivers**: Hardware drivers (drivers/*)
- **tools**: Development tools (tools/*.py, mpy-tool.py, pyboard.py, mpremote)
- **tests**: Test suite (tests/*)
- **docs**: Documentation (docs/*.rst, *.md)
- **build_system**: Makefiles, CMake, build config
- **examples**: Example code (examples/*)

## Port (if port-specific, otherwise null):
Use the port directory name: esp32, stm32, rp2, unix, nrf, samd, mimxrt, renesas-ra, zephyr, webassembly, windows
Set to null for generic code.

## Subsystem (specific area, can be null):
Common subsystems: bluetooth, networking, usb, filesystem, uart, i2c, spi, gpio, adc, pwm, dma, rmt, gc, vm, compiler, types, asyncio, ssl, board_support
Set to null if not applicable.

## Language Context:
Determined by file extension:
- *.c, *.h → "c_code"
- *.py → "python_code"
- *.rst, *.md → "documentation"
- Makefile, *.mk → "makefile"
- *.cmake, CMakeLists.txt → "cmake"
- *.sh → "shell_script"
- *.yml, *.yaml → "yaml"

## Code Construct (what's being discussed):
- **function**: Function definition or call
- **macro**: C preprocessor macro
- **struct**: C struct definition
- **typedef**: Type definition
- **class**: Python class
- **module**: Python or C module
- **test_case**: Test function or file
- **documentation_page**: Docs file
- **build_rule**: Makefile rule
- **config**: Configuration setting
- **include**: Header include

## Concern Type (nature of feedback):
- **correctness**: Logic bugs, wrong behavior, edge cases
- **safety**: Memory safety, alignment, ISR context, undefined behavior
- **api_design**: Function signatures, naming, public interfaces
- **style**: Formatting, naming conventions, code organization
- **performance**: Speed, efficiency, optimization
- **portability**: Cross-platform compatibility, compiler differences
- **maintainability**: Code clarity, DRY, file size, complexity
- **testing**: Test coverage, test correctness
- **documentation**: Docs completeness, clarity, accuracy
- **security**: Security vulnerabilities, input validation
- **compatibility**: CPython compatibility, API stability
- **architecture**: System design, module structure, separation of concerns

## Feedback Type (how it's phrased):
- **question**: "Is this?", "Can we?", "Should this?"
- **suggestion**: "I think", "maybe", "consider", "better to"
- **requirement**: "Please", "Need to", "Must"
- **information**: Explaining, providing context, noting changes
- **praise**: "Thanks", "Good", "Fantastic"
- **merge**: "Merged in [hash]"

## is_pattern (reusable across contexts):
**true** if: Applies to multiple PRs, general best practice, recurring concern, teaching a principle
**false** if: Specific to this PR, one-time fix, historical reference, merge/process comment

## cpython_related:
**true** if comment mentions CPython compatibility, PEP standards, or Python standard library behavior
**false** otherwise

## has_code_suggestion:
**true** if comment includes specific code examples, function names, or implementation suggestions
**false** if purely conceptual or questioning

## Keywords (2-5 technical terms):
Extract key nouns and concepts: function/module names, technical concepts, standards, actions
Format as JSON array: ["term1", "term2", "term3"]

# Example Categorizations

## Example 1: Python Style
Comment: "No spaces around "=" in keyword args."
→ {{
  "comment_num": 1,
  "domain": "code_style",
  "theme": "PEP 8 keyword argument formatting",
  "severity": "nitpick",
  "is_style_example": true,
  "component": "drivers",
  "port": null,
  "subsystem": null,
  "language_context": "python_code",
  "code_construct": "function",
  "concern_type": "style",
  "feedback_type": "requirement",
  "is_pattern": true,
  "cpython_related": true,
  "has_code_suggestion": false,
  "keywords": ["PEP 8", "spacing", "keyword arguments"]
}}

## Example 2: ISR Context
Comment: "Is this USB callback actually an ISR? Or should we instead be using `vTaskNotifyGive(mp_main_task_handle)` instead?"
→ {{
  "comment_num": 1,
  "domain": "correctness",
  "theme": "verify ISR context and use appropriate RTOS primitives",
  "severity": "blocking",
  "is_style_example": true,
  "component": "port_specific",
  "port": "esp32",
  "subsystem": "usb",
  "language_context": "c_code",
  "code_construct": "function",
  "concern_type": "correctness",
  "feedback_type": "question",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["ISR", "RTOS", "callback", "vTaskNotifyGive"]
}}

## Example 3: Documentation
Comment: "Better to use `machine.idle()` here so it doesn't use power unnecessarily while waiting."
→ {{
  "comment_num": 1,
  "domain": "documentation",
  "theme": "documentation code examples should demonstrate best practices",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "docs",
  "port": "rp2",
  "subsystem": "networking",
  "language_context": "documentation",
  "code_construct": "documentation_page",
  "concern_type": "correctness",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["code example", "best practice", "power", "idle"]
}}

# Comments to Categorize

{comments_text}

# Instructions
Categorize each comment using all 13 fields. Focus on the PRIMARY concern for domain. Be specific with themes. Include 2-5 relevant keywords. Set port and subsystem to null if not applicable.

Respond ONLY with the JSON matching the schema - no other text."""


def get_db_connection():
    """Get database connection."""
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    return sqlite3.connect(DB_PATH)


def get_domain_id_map(conn):
    """Get mapping of domain names to IDs."""
    cursor = conn.execute("SELECT id, name FROM domains")
    return {row[1]: row[0] for row in cursor.fetchall()}


def get_checkpoint(conn):
    """Get the last processed checkpoint."""
    cursor = conn.execute(
        "SELECT value FROM sync_state WHERE key = 'categorize_headless_checkpoint'"
    )
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def set_checkpoint(conn, checkpoint):
    """Store the categorization checkpoint."""
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
        ("categorize_headless_checkpoint", str(checkpoint)),
    )
    conn.commit()


def get_uncategorized_comments(conn, limit, offset=0):
    """Get uncategorized comments from all types."""
    comments = []

    # Review comments
    cursor = conn.execute(
        """
        SELECT id, 'review_comment' as type, body, diff_hunk
        FROM review_comments
        WHERE id NOT IN (
            SELECT comment_id FROM comment_categories
            WHERE comment_type = 'review_comment'
        )
        ORDER BY id
        LIMIT ? OFFSET ?
    """,
        (limit, offset),
    )
    for row in cursor.fetchall():
        comments.append({"id": row[0], "type": row[1], "body": row[2], "context": row[3]})
        if len(comments) >= limit:
            break

    # Issue comments (only if we need more)
    if len(comments) < limit:
        cursor = conn.execute(
            """
            SELECT id, 'issue_comment' as type, body, NULL
            FROM issue_comments
            WHERE id NOT IN (
                SELECT comment_id FROM comment_categories
                WHERE comment_type = 'issue_comment'
            )
            ORDER BY id
            LIMIT ? OFFSET ?
        """,
            (limit - len(comments), max(0, offset - 6842)),
        )
        for row in cursor.fetchall():
            comments.append({"id": row[0], "type": row[1], "body": row[2], "context": row[3]})
            if len(comments) >= limit:
                break

    # Reviews (only if we need more)
    if len(comments) < limit:
        cursor = conn.execute(
            """
            SELECT id, 'review' as type, body, NULL
            FROM reviews
            WHERE body IS NOT NULL AND body != ''
            AND id NOT IN (
                SELECT comment_id FROM comment_categories
                WHERE comment_type = 'review'
            )
            ORDER BY id
            LIMIT ? OFFSET ?
        """,
            (limit - len(comments), max(0, offset - 6842 - 11379)),
        )
        for row in cursor.fetchall():
            comments.append({"id": row[0], "type": row[1], "body": row[2], "context": row[3]})

    return comments


def format_comments_for_prompt(comments):
    """Format comments for the prompt."""
    formatted = []
    for i, comment in enumerate(comments, 1):
        body = (comment["body"] or "").strip()
        context = comment["context"] or ""

        comment_text = f"## Comment {i}\n"
        if context:
            comment_text += f"**Diff context:**\n```\n{context}\n```\n\n"
        comment_text += f"**Comment text:**\n{body}\n"
        formatted.append(comment_text)

    return "\n".join(formatted)


def categorize_batch(comments):
    """Use Claude CLI to categorize a batch of comments."""
    comments_text = format_comments_for_prompt(comments)
    prompt = PROMPT_TEMPLATE.format(comments_text=comments_text)

    try:
        cmd = [
            "claude",
            "-p",
            "--model", "haiku",
            "--output-format", "json",
            "--json-schema", json.dumps(CATEGORIZATION_SCHEMA),
            "--no-session-persistence",
        ]

        # Strip CLAUDECODE env var to allow nested CLI invocation
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, check=True, timeout=TIMEOUT_SECONDS,
            env=env,
        )
        response = json.loads(result.stdout)
        # Claude CLI wraps structured output in "structured_output" field
        structured = response.get("structured_output", {})
        return structured.get("categorizations", [])
    except subprocess.TimeoutExpired:
        print(f"  Error: Claude CLI timed out", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as e:
        print(f"  Error running Claude CLI: {e}", file=sys.stderr)
        print(f"  Stderr: {e.stderr}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"  Error parsing JSON response: {e}", file=sys.stderr)
        print(f"  Output: {result.stdout}", file=sys.stderr)
        return None


def mark_batch_as_failed(conn, comments):
    """Mark a batch of comments as failed so they're skipped in future runs."""
    for comment in comments:
        try:
            # Insert a placeholder categorization to mark as processed
            conn.execute(
                """
                INSERT OR IGNORE INTO comment_categories (
                    comment_id, comment_type, domain_id, theme, severity,
                    is_style_example, categorized_at, component, language_context,
                    code_construct, concern_type, feedback_type, is_pattern,
                    cpython_related, has_code_suggestion, keywords
                ) VALUES (?, ?, 12, 'FAILED_CATEGORIZATION', 'suggestion', 0, ?, 'tools',
                          'c_code', 'function', 'correctness', 'information', 0, 0, 0, '["failed"]')
            """,
                (comment["id"], comment["type"], datetime.now().isoformat()),
            )
        except sqlite3.Error as e:
            print(f"  Error marking comment {comment['id']} as failed: {e}", file=sys.stderr)
    conn.commit()


def store_categorizations(conn, comments, categorizations, domain_id_map):
    """Store categorizations in database."""
    severity_map = {"blocking": "blocking", "suggestion": "suggestion", "nitpick": "nitpick"}

    stored_count = 0
    for cat in categorizations:
        comment_num = cat["comment_num"]
        if comment_num < 1 or comment_num > len(comments):
            print(f"  Warning: Invalid comment_num {comment_num}", file=sys.stderr)
            continue

        comment = comments[comment_num - 1]
        domain_id = domain_id_map.get(cat["domain"])

        if not domain_id:
            print(f"  Warning: Unknown domain '{cat['domain']}'", file=sys.stderr)
            continue

        severity = severity_map.get(cat["severity"])
        if not severity:
            print(f"  Warning: Invalid severity '{cat['severity']}'", file=sys.stderr)
            continue

        # Validate keywords
        keywords = cat.get("keywords", [])
        if not isinstance(keywords, list) or len(keywords) < 2 or len(keywords) > 5:
            print(f"  Warning: Invalid keywords for comment {comment_num}: {keywords}", file=sys.stderr)
            continue

        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO comment_categories (
                    comment_id, comment_type, domain_id, theme, severity,
                    is_style_example, categorized_at,
                    component, port, subsystem, language_context, code_construct,
                    concern_type, feedback_type, is_pattern, cpython_related,
                    has_code_suggestion, keywords
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    comment["id"],
                    comment["type"],
                    domain_id,
                    cat["theme"],
                    severity,
                    1 if cat["is_style_example"] else 0,
                    datetime.now().isoformat(),
                    cat["component"],
                    cat.get("port"),  # Can be None/null
                    cat.get("subsystem"),  # Can be None/null
                    cat["language_context"],
                    cat["code_construct"],
                    cat["concern_type"],
                    cat["feedback_type"],
                    1 if cat["is_pattern"] else 0,
                    1 if cat["cpython_related"] else 0,
                    1 if cat["has_code_suggestion"] else 0,
                    json.dumps(keywords),
                ),
            )
            stored_count += 1
        except sqlite3.Error as e:
            print(
                f"  Error storing categorization for comment {comment['id']}: {e}",
                file=sys.stderr,
            )

    conn.commit()
    return stored_count


def main():
    print("Starting categorization using Claude CLI in headless mode...")
    print(f"Batch size: {BATCH_SIZE}, Max budget: ${MAX_BUDGET}")

    conn = get_db_connection()
    domain_id_map = get_domain_id_map(conn)

    # Get total uncategorized count
    cursor = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM review_comments WHERE id NOT IN (
                SELECT comment_id FROM comment_categories WHERE comment_type = 'review_comment'
            )) +
            (SELECT COUNT(*) FROM issue_comments WHERE id NOT IN (
                SELECT comment_id FROM comment_categories WHERE comment_type = 'issue_comment'
            )) +
            (SELECT COUNT(*) FROM reviews WHERE body IS NOT NULL AND body != '' AND id NOT IN (
                SELECT comment_id FROM comment_categories WHERE comment_type = 'review'
            ))
    """
    )
    total_uncategorized = cursor.fetchone()[0]
    print(f"Total uncategorized comments: {total_uncategorized}")

    if total_uncategorized == 0:
        print("No uncategorized comments found.")
        return

    checkpoint = get_checkpoint(conn)
    processed = checkpoint
    failed_batches = 0
    max_failures = 5  # Stop after 5 consecutive failures

    while processed < total_uncategorized:
        batch_comments = get_uncategorized_comments(conn, BATCH_SIZE, offset=0)

        if not batch_comments:
            break

        print(
            f"\nProcessing batch: {processed + 1}-{processed + len(batch_comments)} / {total_uncategorized}"
        )

        # Retry on timeout (up to 2 retries)
        categorizations = None
        for attempt in range(3):
            categorizations = categorize_batch(batch_comments)
            if categorizations is not None:
                break
            if attempt < 2:
                print(f"  Retry {attempt + 1}/2...")

        if categorizations is None:
            print("  Failed to categorize batch after 3 attempts, marking as failed and skipping.")
            mark_batch_as_failed(conn, batch_comments)
            failed_batches += 1
            if failed_batches >= max_failures:
                print(f"  Too many consecutive failures ({max_failures}), stopping.")
                break
            # Update checkpoint to skip this batch
            processed += len(batch_comments)
            set_checkpoint(conn, processed)
            continue

        # Reset failure counter on success
        failed_batches = 0

        if len(categorizations) != len(batch_comments):
            print(
                f"  Warning: Expected {len(batch_comments)} categorizations, got {len(categorizations)}"
            )

        stored = store_categorizations(
            conn, batch_comments, categorizations, domain_id_map
        )
        print(f"  Stored {stored}/{len(batch_comments)} categorizations")

        processed += stored
        set_checkpoint(conn, processed)

        # Add delay to avoid rate limiting
        time.sleep(2)

    print(f"\nCategorization complete! Processed {processed} comments.")
    conn.close()


if __name__ == "__main__":
    main()
