#!/usr/bin/env python3
"""
Load all 55 manually categorized samples into the database.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reviews.db"

# All 55 categorizations (10 original + 45 new)
samples = [
    # Original 10 samples (already loaded, but included for completeness)
    # Python batch (10 samples)
    {
        "pr": 11897, "text": "See #12224 for a fix",
        "cat": {
            "domain": "correctness", "theme": "reference to related PR with fix",
            "severity": "suggestion", "is_style_example": 0,
            "component": "extmod", "port": None, "subsystem": "asyncio",
            "language_context": "python_code", "code_construct": "module",
            "concern_type": "correctness", "feedback_type": "information",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["fix", "reference", "PR"]
        }
    },
    {
        "pr": 7691, "text": "IIRC this is part of the public API",
        "cat": {
            "domain": "api_design", "theme": "preserve public API for extensibility",
            "severity": "blocking", "is_style_example": 1,
            "component": "drivers", "port": None, "subsystem": None,
            "language_context": "python_code", "code_construct": "class",
            "concern_type": "api_design", "feedback_type": "requirement",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["public API", "override", "extensibility", "ORDER"]
        }
    },
    {
        "pr": 6527, "text": "yes, also to be removed",
        "cat": {
            "domain": "code_style", "theme": "confirmation of code to remove",
            "severity": "suggestion", "is_style_example": 0,
            "component": "tools", "port": None, "subsystem": None,
            "language_context": "python_code", "code_construct": "function",
            "concern_type": "maintainability", "feedback_type": "information",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["remove", "cleanup"]
        }
    },
    {
        "pr": 8577, "text": "This method name and the ones below are not consistent",
        "cat": {
            "domain": "api_design", "theme": "consistent naming across similar drivers",
            "severity": "suggestion", "is_style_example": 1,
            "component": "drivers", "port": "nrf", "subsystem": None,
            "language_context": "python_code", "code_construct": "function",
            "concern_type": "api_design", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["naming", "consistency", "drivers", "API"]
        }
    },
    {
        "pr": 10991, "text": "Yes you are right. So I'll need to check",
        "cat": {
            "domain": "correctness", "theme": "need to verify edge case behavior",
            "severity": "suggestion", "is_style_example": 1,
            "component": "extmod", "port": None, "subsystem": "asyncio",
            "language_context": "python_code", "code_construct": "function",
            "concern_type": "correctness", "feedback_type": "information",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["edge case", "exception", "verification"]
        }
    },
    {
        "pr": 17112, "text": "I think you need to leave the",
        "cat": {
            "domain": "error_handling", "theme": "preserve user-friendly error messages over exceptions",
            "severity": "suggestion", "is_style_example": 1,
            "component": "tools", "port": None, "subsystem": None,
            "language_context": "python_code", "code_construct": "function",
            "concern_type": "maintainability", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["error handling", "user experience", "help message"]
        }
    },
    {
        "pr": 18381, "text": "Is this type checking necessary",
        "cat": {
            "domain": "code_style", "theme": "manage file size and complexity",
            "severity": "suggestion", "is_style_example": 1,
            "component": "tools", "port": None, "subsystem": None,
            "language_context": "python_code", "code_construct": "function",
            "concern_type": "maintainability", "feedback_type": "question",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["file size", "complexity", "type checking", "necessity"]
        }
    },
    {
        "pr": 3435, "text": "No spaces around",
        "cat": {
            "domain": "code_style", "theme": "PEP 8 keyword argument formatting",
            "severity": "nitpick", "is_style_example": 1,
            "component": "drivers", "port": None, "subsystem": None,
            "language_context": "python_code", "code_construct": "function",
            "concern_type": "style", "feedback_type": "requirement",
            "is_pattern": 1, "cpython_related": 1, "has_code_suggestion": 0,
            "keywords": ["PEP 8", "spacing", "keyword arguments", "formatting"]
        }
    },
    {
        "pr": 17321, "text": "Instead of checking if it's an instance",
        "cat": {
            "domain": "error_handling", "theme": "simplify exception handling logic",
            "severity": "suggestion", "is_style_example": 1,
            "component": "tools", "port": None, "subsystem": None,
            "language_context": "python_code", "code_construct": "function",
            "concern_type": "maintainability", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["exception", "simplification", "OSError", "control flow"]
        }
    },
    {
        "pr": 5800, "text": "Since the long-form option for the baudrate",
        "cat": {
            "domain": "api_design", "theme": "consistent naming between CLI args and env variables",
            "severity": "suggestion", "is_style_example": 1,
            "component": "tools", "port": None, "subsystem": None,
            "language_context": "python_code", "code_construct": "config",
            "concern_type": "api_design", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["naming", "environment variable", "CLI", "consistency"]
        }
    },
    # Documentation batch (5 samples)
    {
        "pr": 16661, "text": "IMO this should be moved down",
        "cat": {
            "domain": "documentation", "theme": "documentation structure and placement",
            "severity": "suggestion", "is_style_example": 1,
            "component": "docs", "port": None, "subsystem": "networking",
            "language_context": "documentation", "code_construct": "documentation_page",
            "concern_type": "documentation", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["structure", "placement", "heading", "organization"]
        }
    },
    {
        "pr": 7620, "text": "Need to add the",
        "cat": {
            "domain": "documentation", "theme": "missing function signature in documentation",
            "severity": "blocking", "is_style_example": 0,
            "component": "docs", "port": None, "subsystem": None,
            "language_context": "documentation", "code_construct": "documentation_page",
            "concern_type": "documentation", "feedback_type": "requirement",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["function signature", "completeness", "freeze"]
        }
    },
    {
        "pr": 15942, "text": "I think it would be better if this URL",
        "cat": {
            "domain": "documentation", "theme": "use full URLs for direct file access",
            "severity": "suggestion", "is_style_example": 1,
            "component": "docs", "port": "samd", "subsystem": "board_support",
            "language_context": "documentation", "code_construct": "documentation_page",
            "concern_type": "documentation", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["URL", "direct link", "usability", "deployment"]
        }
    },
    {
        "pr": 16475, "text": "Better to use `machine.idle()`",
        "cat": {
            "domain": "documentation", "theme": "documentation code examples should demonstrate best practices",
            "severity": "suggestion", "is_style_example": 1,
            "component": "docs", "port": "rp2", "subsystem": "networking",
            "language_context": "documentation", "code_construct": "documentation_page",
            "concern_type": "correctness", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["code example", "best practice", "power", "idle"]
        }
    },
    {
        "pr": 5184, "text": "This kind of historical language",
        "cat": {
            "domain": "documentation", "theme": "keep quick reference brief and focused",
            "severity": "suggestion", "is_style_example": 1,
            "component": "docs", "port": "esp32", "subsystem": "rmt",
            "language_context": "documentation", "code_construct": "documentation_page",
            "concern_type": "documentation", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["brevity", "quick reference", "focus", "historical"]
        }
    },
    # Build system batch (5 samples)
    {
        "pr": 17001, "text": "You don't need this if the manifest",
        "cat": {
            "domain": "build_system", "theme": "remove unnecessary configuration when using defaults",
            "severity": "suggestion", "is_style_example": 1,
            "component": "port_specific", "port": "rp2", "subsystem": "board_support",
            "language_context": "cmake", "code_construct": "config",
            "concern_type": "maintainability", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["unnecessary", "default", "manifest", "cleanup"]
        }
    },
    {
        "pr": 9072, "text": "I think this should be",
        "cat": {
            "domain": "build_system", "theme": "consistent build variable naming",
            "severity": "suggestion", "is_style_example": 1,
            "component": "port_specific", "port": "stm32", "subsystem": None,
            "language_context": "makefile", "code_construct": "build_rule",
            "concern_type": "maintainability", "feedback_type": "question",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["variable naming", "MBOOT", "USE_", "consistency"]
        }
    },
    {
        "pr": 15158, "text": "Is this line needed, since jlink",
        "cat": {
            "domain": "build_system", "theme": "question necessity of explicit default configuration",
            "severity": "suggestion", "is_style_example": 1,
            "component": "port_specific", "port": "nrf", "subsystem": "board_support",
            "language_context": "makefile", "code_construct": "config",
            "concern_type": "maintainability", "feedback_type": "question",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["necessity", "default", "jlink", "flasher"]
        }
    },
    {
        "pr": 16960, "text": "For this example, I'd suggest keeping it as minimal",
        "cat": {
            "domain": "documentation", "theme": "keep examples minimal and consistent with other implementations",
            "severity": "suggestion", "is_style_example": 1,
            "component": "examples", "port": None, "subsystem": None,
            "language_context": "makefile", "code_construct": "build_rule",
            "concern_type": "documentation", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["minimal", "example", "consistency", "cmake"]
        }
    },
    {
        "pr": 9054, "text": "How about calling this option",
        "cat": {
            "domain": "build_system", "theme": "descriptive naming for build options",
            "severity": "suggestion", "is_style_example": 1,
            "component": "port_specific", "port": "stm32", "subsystem": None,
            "language_context": "makefile", "code_construct": "config",
            "concern_type": "api_design", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["naming", "MICROPY_HW_", "descriptive", "build option"]
        }
    },
    # Architecture batch (10 samples) - continuing...
    {
        "pr": 15727, "text": "I don't understand why changing",
        "cat": {
            "domain": "architecture", "theme": "request explanation of configuration logic flow",
            "severity": "suggestion", "is_style_example": 1,
            "component": "port_specific", "port": "esp32", "subsystem": "usb",
            "language_context": "c_code", "code_construct": "config",
            "concern_type": "maintainability", "feedback_type": "question",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["configuration", "logic flow", "explanation"]
        }
    },
    {
        "pr": 5745, "text": "It will compile and run",
        "cat": {
            "domain": "architecture", "theme": "partial language feature support - compile but don't store",
            "severity": "suggestion", "is_style_example": 0,
            "component": "py_core", "port": None, "subsystem": "compiler",
            "language_context": "c_code", "code_construct": "function",
            "concern_type": "compatibility", "feedback_type": "information",
            "is_pattern": 0, "cpython_related": 1, "has_code_suggestion": 0,
            "keywords": ["raise from", "exception cause", "compiler support", "warnings"]
        }
    },
    {
        "pr": 8495, "text": "`pyboard.py` is a low-level library",
        "cat": {
            "domain": "architecture", "theme": "libraries should not output - calling code controls output",
            "severity": "suggestion", "is_style_example": 1,
            "component": "tools", "port": None, "subsystem": None,
            "language_context": "python_code", "code_construct": "function",
            "concern_type": "api_design", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["library", "separation of concerns", "output", "programmatic use"]
        }
    },
    {
        "pr": 6838, "text": "I'm not sure it's the right approach",
        "cat": {
            "domain": "architecture", "theme": "prefer local state over globals for thread safety",
            "severity": "suggestion", "is_style_example": 1,
            "component": "extmod", "port": None, "subsystem": None,
            "language_context": "c_code", "code_construct": "function",
            "concern_type": "safety", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["thread safety", "globals", "local state", "context struct"]
        }
    },
    {
        "pr": 14318, "text": "Also added a fix",
        "cat": {
            "domain": "correctness", "theme": "fix initialization for updated dependency",
            "severity": "suggestion", "is_style_example": 0,
            "component": "port_specific", "port": "webassembly", "subsystem": None,
            "language_context": "c_code", "code_construct": "module",
            "concern_type": "compatibility", "feedback_type": "information",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["initialization", "Emscripten", "fix"]
        }
    },
    {
        "pr": 4900, "text": "When does such a case arise",
        "cat": {
            "domain": "architecture", "theme": "ports control output - can translate at output layer",
            "severity": "suggestion", "is_style_example": 1,
            "component": "py_core", "port": None, "subsystem": None,
            "language_context": "c_code", "code_construct": "function",
            "concern_type": "architecture", "feedback_type": "question",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["port responsibility", "output", "translation", "abstraction"]
        }
    },
    {
        "pr": 16147, "text": "Once #16216 is merged",
        "cat": {
            "domain": "testing", "theme": "plan for test framework migration",
            "severity": "suggestion", "is_style_example": 0,
            "component": "tests", "port": None, "subsystem": None,
            "language_context": "python_code", "code_construct": "test_case",
            "concern_type": "maintainability", "feedback_type": "information",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["unittest", "refactoring", "test framework", "portability"]
        }
    },
    {
        "pr": 8185, "text": "Fantastic",
        "cat": {
            "domain": "architecture", "theme": "approval of design approach",
            "severity": "nitpick", "is_style_example": 0,
            "component": "port_specific", "port": "stm32", "subsystem": None,
            "language_context": "c_code", "code_construct": "module",
            "concern_type": "api_design", "feedback_type": "praise",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["approval", "FDCAN", "configuration"]
        }
    },
    {
        "pr": 41, "text": "How about naming it",
        "cat": {
            "domain": "architecture", "theme": "config file naming conventions and inheritance pattern",
            "severity": "suggestion", "is_style_example": 1,
            "component": "py_core", "port": None, "subsystem": None,
            "language_context": "c_code", "code_construct": "config",
            "concern_type": "maintainability", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["config", "naming", "inheritance", "include", "default"]
        }
    },
    {
        "pr": 10830, "text": "Thanks for the contribution. But see",
        "cat": {
            "domain": "architecture", "theme": "cross-reference duplicate work and ongoing discussion",
            "severity": "suggestion", "is_style_example": 0,
            "component": "port_specific", "port": "zephyr", "subsystem": None,
            "language_context": "c_code", "code_construct": "module",
            "concern_type": "maintainability", "feedback_type": "information",
            "is_pattern": 0, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["duplicate", "cross-reference", "discussion", "naming"]
        }
    },
    # Port-specific batch (10 samples)
    {
        "pr": 7779, "text": "instead of this guarded",
        "cat": {
            "domain": "code_style", "theme": "simplify control flow with early return",
            "severity": "suggestion", "is_style_example": 1,
            "component": "port_specific", "port": "stm32", "subsystem": "usb",
            "language_context": "c_code", "code_construct": "function",
            "concern_type": "maintainability", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["early return", "control flow", "simplification", "else"]
        }
    },
    {
        "pr": 8228, "text": "As above, maybe use",
        "cat": {
            "domain": "api_design", "theme": "use consistent API across similar code",
            "severity": "suggestion", "is_style_example": 0,
            "component": "port_specific", "port": "esp32", "subsystem": "adc",
            "language_context": "python_code", "code_construct": "function",
            "concern_type": "api_design", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["ADC", "API", "consistency", "read_uv"]
        }
    },
    {
        "pr": 12845, "text": "Is this USB callback actually an ISR",
        "cat": {
            "domain": "correctness", "theme": "verify ISR context and use appropriate RTOS primitives",
            "severity": "blocking", "is_style_example": 1,
            "component": "port_specific", "port": "esp32", "subsystem": "usb",
            "language_context": "c_code", "code_construct": "function",
            "concern_type": "correctness", "feedback_type": "question",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["ISR", "RTOS", "callback", "vTaskNotifyGive", "context"]
        }
    },
    {
        "pr": 12845, "text": "I think it would be good to put this in a function called",
        "cat": {
            "domain": "api_design", "theme": "extract HAL helper function for reusability",
            "severity": "suggestion", "is_style_example": 1,
            "component": "port_specific", "port": "esp32", "subsystem": None,
            "language_context": "c_code", "code_construct": "function",
            "concern_type": "maintainability", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["HAL", "helper function", "mp_hal_", "extraction"]
        }
    },
    {
        "pr": 6501, "text": "perhaps make the registers",
        "cat": {
            "domain": "code_style", "theme": "replace magic numbers with named constants",
            "severity": "suggestion", "is_style_example": 1,
            "component": "port_specific", "port": "stm32", "subsystem": "board_support",
            "language_context": "python_code", "code_construct": "config",
            "concern_type": "maintainability", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["magic numbers", "constants", "const", "registers"]
        }
    },
    # This one already exists in original 10, skip duplicate
    # {
    #     "pr": 10739, "text": "Better to not use negation",
    # },
    {
        "pr": 3578, "text": "Putting the ULP class",
        "cat": {
            "domain": "architecture", "theme": "file naming matches module structure",
            "severity": "suggestion", "is_style_example": 1,
            "component": "port_specific", "port": "esp32", "subsystem": None,
            "language_context": "c_code", "code_construct": "module",
            "concern_type": "maintainability", "feedback_type": "information",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["file naming", "module", "convention", "esp32_"]
        }
    },
    {
        "pr": 13096, "text": "this file now needs to include",
        "cat": {
            "domain": "correctness", "theme": "add missing include for function definition",
            "severity": "blocking", "is_style_example": 0,
            "component": "port_specific", "port": "rp2", "subsystem": "networking",
            "language_context": "c_code", "code_construct": "include",
            "concern_type": "correctness", "feedback_type": "requirement",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["include", "header", "dependency", "function definition"]
        }
    },
    {
        "pr": 3945, "text": "Zero length arrays may give problems",
        "cat": {
            "domain": "portability", "theme": "avoid zero-length arrays for compiler compatibility",
            "severity": "suggestion", "is_style_example": 1,
            "component": "port_specific", "port": "stm32", "subsystem": "filesystem",
            "language_context": "c_code", "code_construct": "typedef",
            "concern_type": "portability", "feedback_type": "suggestion",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 1,
            "keywords": ["zero-length array", "compiler", "portability", "uint8_t"]
        }
    },
    {
        "pr": 17971, "text": "Please put this on one line",
        "cat": {
            "domain": "code_style", "theme": "match surrounding code formatting",
            "severity": "nitpick", "is_style_example": 1,
            "component": "port_specific", "port": "esp32", "subsystem": "i2c",
            "language_context": "c_code", "code_construct": "function",
            "concern_type": "style", "feedback_type": "requirement",
            "is_pattern": 1, "cpython_related": 0, "has_code_suggestion": 0,
            "keywords": ["formatting", "consistency", "one line", "surrounding code"]
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
    updated = 0

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

        # Check if already exists
        cursor = conn.execute(
            "SELECT id FROM comment_categories WHERE comment_id = ? AND comment_type = ?",
            (comment_id, comment_type)
        )
        exists = cursor.fetchone()

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

        if exists:
            print(f"↻ Updated PR #{pr}: {cat['domain']} - {cat['theme'][:50]}")
            updated += 1
        else:
            print(f"✓ Loaded PR #{pr}: {cat['domain']} - {cat['theme'][:50]}")
            loaded += 1

    conn.commit()
    conn.close()

    print(f"\nLoaded {loaded} new samples, updated {updated}, skipped {skipped}")
    print(f"Total categorized: {loaded + updated}")


if __name__ == "__main__":
    load_samples()
