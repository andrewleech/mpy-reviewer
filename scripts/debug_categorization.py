#!/usr/bin/env python3
"""
Debug the enhanced categorization with a minimal test.
"""

import json
import subprocess
import sys

# Minimal test comment
TEST_COMMENT = """## Comment 1
**Comment text:**
No spaces around "=" in keyword args.
"""

# Same schema as categorize_headless.py (simplified)
SCHEMA = {
    "type": "object",
    "properties": {
        "categorizations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "comment_num": {"type": "integer"},
                    "domain": {"type": "string"},
                    "theme": {"type": "string"},
                    "severity": {"type": "string"},
                    "is_style_example": {"type": "boolean"},
                    "component": {"type": "string"},
                    "port": {"type": ["string", "null"]},
                    "subsystem": {"type": ["string", "null"]},
                    "language_context": {"type": "string"},
                    "code_construct": {"type": "string"},
                    "concern_type": {"type": "string"},
                    "feedback_type": {"type": "string"},
                    "is_pattern": {"type": "boolean"},
                    "cpython_related": {"type": "boolean"},
                    "has_code_suggestion": {"type": "boolean"},
                    "keywords": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["comment_num", "domain", "theme", "severity", "is_style_example",
                             "component", "language_context", "code_construct", "concern_type",
                             "feedback_type", "is_pattern", "cpython_related",
                             "has_code_suggestion", "keywords"]
            }
        }
    },
    "required": ["categorizations"]
}

PROMPT = f"""Categorize this MicroPython review comment using 13 fields.

Comment:
{TEST_COMMENT}

Return JSON with: comment_num, domain, theme, severity, is_style_example, component, port, subsystem, language_context, code_construct, concern_type, feedback_type, is_pattern, cpython_related, has_code_suggestion, keywords.

Example:
{{"categorizations": [{{"comment_num": 1, "domain": "code_style", "theme": "PEP 8 spacing", "severity": "nitpick", "is_style_example": true, "component": "tools", "port": null, "subsystem": null, "language_context": "python_code", "code_construct": "function", "concern_type": "style", "feedback_type": "requirement", "is_pattern": true, "cpython_related": true, "has_code_suggestion": false, "keywords": ["PEP 8", "spacing", "keyword args"]}}]}}

Respond with JSON only."""

print("Testing Claude CLI with enhanced schema...")
print(f"Prompt length: {len(PROMPT)} chars")
print(f"Schema: {len(json.dumps(SCHEMA))} chars")
print()

cmd = [
    "claude",
    "-p",
    "--model", "haiku",
    "--output-format", "json",
    "--json-schema", json.dumps(SCHEMA),
    "--tools", "",
    "--max-budget-usd", "1.00",
    "--no-session-persistence",
    PROMPT
]

print("Running Claude CLI...")
try:
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
    print("✓ Success!")
    print(f"\nOutput:\n{result.stdout}")

    # Try to parse JSON
    try:
        data = json.loads(result.stdout)
        print(f"\n✓ Valid JSON")
        print(f"Categorizations: {len(data.get('categorizations', []))}")
        if data.get('categorizations'):
            cat = data['categorizations'][0]
            print(f"  Domain: {cat.get('domain')}")
            print(f"  Component: {cat.get('component')}")
            print(f"  Keywords: {cat.get('keywords')}")
    except json.JSONDecodeError as e:
        print(f"✗ JSON parse error: {e}")

except subprocess.TimeoutExpired:
    print("✗ Timeout after 120s")
except subprocess.CalledProcessError as e:
    print(f"✗ Error: {e}")
    print(f"Stderr: {e.stderr}")
except Exception as e:
    print(f"✗ Unexpected error: {e}")
