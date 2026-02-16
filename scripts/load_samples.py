#!/usr/bin/env python3
"""
Load manually categorized samples into the database.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"

# Manual categorizations from our analysis
# Format: (pr_number, comment_text_prefix, categorization)
samples = [
    # Batch 1 samples
    {
        "pr": 6127, "text": "this can just be a `bool`",
        "cat": {
            "domain": "code_style", "theme": "use simpler bool type instead of int",
            "severity": "suggestion", "is_style_example": 0,
            "component": "port_specific", "port": "esp32", "subsystem": "rmt",
            "language_context": "c_code", "code_construct": "typedef",
            "concern_type": "style", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["bool", "type simplification", "integer"]
        }
    },
    {
        "pr": 12652, "text": "Unfortunately this doesn't fully work on Linux",
        "cat": {
            "domain": "portability", "theme": "flush syscall fails on non-tty in Linux subprocess",
            "severity": "blocking", "is_style_example": 0,
            "component": "extmod", "port": None, "subsystem": "filesystem",
            "language_context": "c_code", "code_construct": "function",
            "concern_type": "portability", "feedback_type": "requirement",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["flush", "syscall", "EINVAL", "tty", "subprocess", "Linux"]
        }
    },
    {
        "pr": 9373, "text": "Yes, good to always wrap macro args in parenthesis",
        "cat": {
            "domain": "correctness", "theme": "macro argument evaluation - side effects from double evaluation",
            "severity": "blocking", "is_style_example": 1,
            "component": "py_core", "port": None, "subsystem": "types",
            "language_context": "c_code", "code_construct": "macro",
            "concern_type": "correctness", "feedback_type": "question",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["macro", "parenthesis", "evaluation", "side effects"]
        }
    },
    {
        "pr": 16691, "text": "Reading this again, the word",
        "cat": {
            "domain": "documentation", "theme": "documentation wording clarity",
            "severity": "nitpick", "is_style_example": 0,
            "component": "docs", "port": None, "subsystem": None,
            "language_context": "documentation", "code_construct": "documentation_page",
            "concern_type": "documentation", "feedback_type": "suggestion",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["wording", "clarity", "array", "methods"]
        }
    },
    {
        "pr": 17171, "text": "Do you want to have the OPENMV_N6",
        "cat": {
            "domain": "architecture", "theme": "board integration strategy and mboot compatibility",
            "severity": "suggestion", "is_style_example": 0,
            "component": "port_specific", "port": "stm32", "subsystem": "board_support",
            "language_context": "c_code", "code_construct": "config",
            "concern_type": "maintainability", "feedback_type": "question",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["board definition", "mboot", "integration", "OPENMV"]
        }
    },
    {
        "pr": 11897, "text": "I think this function should be called",
        "cat": {
            "domain": "api_design", "theme": "function naming clarity",
            "severity": "suggestion", "is_style_example": 1,
            "component": "extmod", "port": None, "subsystem": "ssl",
            "language_context": "c_code", "code_construct": "function",
            "concern_type": "api_design", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["naming", "function", "ssl", "handshake", "async"]
        }
    },
    {
        "pr": 16225, "text": "Let's add that in a separate test",
        "cat": {
            "domain": "testing", "theme": "test organization - separate test file",
            "severity": "suggestion", "is_style_example": 0,
            "component": "tests", "port": "esp32", "subsystem": "networking",
            "language_context": "python_code", "code_construct": "test_case",
            "concern_type": "maintainability", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["test", "organization", "separate"]
        }
    },
    {
        "pr": 7641, "text": "Changed to use `mp_obj_get_int_truncated()`",
        "cat": {
            "domain": "api_design", "theme": "use MicroPython-specific conversion function",
            "severity": "suggestion", "is_style_example": 0,
            "component": "port_specific", "port": "rp2", "subsystem": "dma",
            "language_context": "c_code", "code_construct": "function",
            "concern_type": "maintainability", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["mp_obj_get_int_truncated", "type conversion", "integer"]
        }
    },
    {
        "pr": 4926, "text": "> but doesn't that mean we're missing coverage",
        "cat": {
            "domain": "testing", "theme": "test coverage for multi-key dictionary ordering",
            "severity": "suggestion", "is_style_example": 1,
            "component": "tests", "port": None, "subsystem": None,
            "language_context": "python_code", "code_construct": "test_case",
            "concern_type": "testing", "feedback_type": "suggestion",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["json", "test coverage", "dictionary", "ordering", "sorted"]
        }
    },
    {
        "pr": 7209, "text": "This could potentially be unaligned",
        "cat": {
            "domain": "portability", "theme": "struct member alignment for cross-platform compatibility",
            "severity": "blocking", "is_style_example": 1,
            "component": "py_core", "port": None, "subsystem": "qstr",
            "language_context": "c_code", "code_construct": "struct",
            "concern_type": "safety", "feedback_type": "requirement",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["alignment", "struct", "qstr", "portability", "memory layout"]
        }
    },
]

def get_domain_id(conn, domain_name):
    """Get domain ID from name."""
    cursor = conn.execute("SELECT id FROM domains WHERE name = ?", (domain_name,))
    row = cursor.fetchone()
    return row[0] if row else None

def find_comment_id(conn, pr_number, text_prefix):
    """Find comment ID by PR number and text prefix."""
    # Try review_comments first
    cursor = conn.execute(
        """SELECT id FROM review_comments
           WHERE pr_number = ? AND body LIKE ?
           LIMIT 1""",
        (pr_number, f"{text_prefix}%")
    )
    row = cursor.fetchone()
    if row:
        return row[0], "review_comment"

    # Try issue_comments
    cursor = conn.execute(
        """SELECT id FROM issue_comments
           WHERE pr_number = ? AND body LIKE ?
           LIMIT 1""",
        (pr_number, f"{text_prefix}%")
    )
    row = cursor.fetchone()
    if row:
        return row[0], "issue_comment"

    return None, None

def load_samples():
    conn = sqlite3.connect(DB_PATH)

    loaded = 0
    skipped = 0

    for sample in samples:
        pr = sample["pr"]
        text = sample["text"]
        cat = sample["cat"]

        # Find the comment
        comment_id, comment_type = find_comment_id(conn, pr, text)

        if not comment_id:
            print(f"✗ Could not find comment in PR #{pr}: '{text[:50]}...'")
            skipped += 1
            continue

        # Get domain ID
        domain_id = get_domain_id(conn, cat["domain"])
        if not domain_id:
            print(f"✗ Unknown domain: {cat['domain']}")
            skipped += 1
            continue

        # Insert or update categorization
        keywords_json = json.dumps(cat["keywords"])

        conn.execute("""
            INSERT OR REPLACE INTO comment_categories (
                comment_id, comment_type, domain_id, theme, severity,
                is_style_example, categorized_at,
                component, port, subsystem, language_context, code_construct,
                concern_type, feedback_type, is_pattern, cpython_related,
                has_code_suggestion, keywords
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            comment_id, comment_type, domain_id, cat["theme"], cat["severity"],
            cat["is_style_example"], datetime.now().isoformat(),
            cat["component"], cat["port"], cat["subsystem"],
            cat["language_context"], cat["code_construct"],
            cat["concern_type"], cat["feedback_type"], cat["is_pattern"],
            cat["cpython_related"], cat["has_code_suggestion"], keywords_json
        ))

        print(f"✓ Loaded PR #{pr}: {cat['domain']} - {cat['theme'][:50]}")
        loaded += 1

    conn.commit()
    conn.close()

    print(f"\nLoaded {loaded} samples, skipped {skipped}")

if __name__ == "__main__":
    load_samples()
