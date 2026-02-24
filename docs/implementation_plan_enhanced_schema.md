# Implementation Plan: Enhanced 13-Field Categorization Script

## Objective

Update `categorize_headless.py` to use the validated 13-field schema instead of the current 4-field schema.

## Current State vs Target State

### Current (4 fields)
```json
{
  "domain": "code_style",
  "theme": "use simpler bool type",
  "severity": "suggestion",
  "is_style_example": false
}
```

### Target (13 fields)
```json
{
  "domain": "code_style",
  "theme": "use simpler bool type instead of int",
  "severity": "suggestion",
  "is_style_example": false,
  "component": "port_specific",
  "port": "esp32",
  "subsystem": "rmt",
  "language_context": "c_code",
  "code_construct": "typedef",
  "concern_type": "style",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": false,
  "keywords": ["bool", "type simplification", "integer"]
}
```

## Implementation Tasks

### Task 1: Update JSON Schema

**File:** `categorize_headless.py` lines 20-58

**Changes:**
- Add 9 new fields to schema
- Define enums for all categorical fields
- Update required fields list

**New fields:**

```python
"component": {
    "type": "string",
    "enum": ["py_core", "extmod", "port_specific", "drivers", "tools",
             "tests", "docs", "build_system", "examples"]
},
"port": {
    "type": ["string", "null"],
    "enum": [null, "esp32", "stm32", "rp2", "unix", "nrf", "samd",
             "mimxrt", "renesas-ra", "zephyr", "webassembly", "windows"]
},
"subsystem": {
    "type": ["string", "null"],
    "enum": [null, "bluetooth", "networking", "usb", "filesystem", "uart",
             "i2c", "spi", "adc", "gpio", "pwm", "dma", "rmt", "gc", "vm",
             "compiler", "types", "asyncio", "ssl", "board_support"]
},
"language_context": {
    "type": "string",
    "enum": ["c_code", "python_code", "documentation", "makefile",
             "cmake", "shell_script", "yaml"]
},
"code_construct": {
    "type": "string",
    "enum": ["function", "macro", "struct", "typedef", "class", "module",
             "test_case", "documentation_page", "build_rule", "config", "include"]
},
"concern_type": {
    "type": "string",
    "enum": ["correctness", "safety", "api_design", "style", "performance",
             "portability", "maintainability", "testing", "documentation",
             "security", "compatibility", "architecture"]
},
"feedback_type": {
    "type": "string",
    "enum": ["question", "suggestion", "requirement", "information", "praise", "merge"]
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
```

**Required fields:**
```python
"required": ["comment_num", "domain", "theme", "severity", "is_style_example",
             "component", "language_context", "code_construct", "concern_type",
             "feedback_type", "is_pattern", "cpython_related",
             "has_code_suggestion", "keywords"]
```

**Note:** `port` and `subsystem` are nullable, not required.

---

### Task 2: Enhance Prompt Template

**File:** `categorize_headless.py` lines 60-120

**Structure:**
1. Context (existing) ✓
2. MicroPython priorities (existing) ✓
3. **NEW:** Enhanced field definitions with examples
4. **NEW:** Decision guidelines for ambiguous cases
5. **NEW:** Example categorizations from our 42 samples
6. Instructions (update)

**Key additions:**

#### Component Classification Guidelines
```
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

Examples:
- tools/mpy-tool.py → component: "tools"
- ports/esp32/machine_uart.c → component: "port_specific"
- py/objtype.c → component: "py_core"
```

#### Port and Subsystem Guidelines
```
## Port (if port-specific, otherwise null):
Use the port directory name: esp32, stm32, rp2, unix, etc.
Set to null for generic code.

Examples:
- ports/esp32/main.c → port: "esp32"
- py/runtime.c → port: null
- docs/library/machine.rst → port: null

## Subsystem (specific area, can be null):
Identify from filename or context. Common subsystems:
- Hardware: bluetooth, usb, uart, i2c, spi, gpio, networking, filesystem
- py_core: gc, vm, compiler, types
- extmod: asyncio, ssl

Examples:
- machine_uart.c → subsystem: "uart"
- modbluetooth.c → subsystem: "bluetooth"
- objtype.c → subsystem: "types"
- general comment → subsystem: null
```

#### Language Context Guidelines
```
## Language Context:
Determined by file extension and content:
- *.c, *.h → "c_code"
- *.py → "python_code"
- *.rst, *.md → "documentation"
- Makefile, *.mk → "makefile"
- *.cmake, CMakeLists.txt → "cmake"

Examples:
- Comment on py/runtime.c → language_context: "c_code"
- Comment on tools/pyboard.py → language_context: "python_code"
- Comment on docs/library/machine.rst → language_context: "documentation"
```

#### Code Construct Guidelines
```
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

Examples:
- "this function should be called X" → code_construct: "function"
- "wrap macro args in parentheses" → code_construct: "macro"
- "this test needs..." → code_construct: "test_case"
```

#### Concern Type Guidelines
```
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

Examples:
- "this could be unaligned" → concern_type: "safety"
- "function should be called X" → concern_type: "api_design"
- "No spaces around =" → concern_type: "style"
- "test coverage for X" → concern_type: "testing"
```

#### Feedback Type Guidelines
```
## Feedback Type (how it's phrased):
- **question**: "Is this?", "Can we?", "Should this?"
- **suggestion**: "I think", "maybe", "consider", "better to"
- **requirement**: "Please", "Need to", "Must"
- **information**: Explaining, providing context, noting changes
- **praise**: "Thanks", "Good", "Fantastic"
- **merge**: "Merged in [hash]"

Examples:
- "Is this necessary?" → feedback_type: "question"
- "I suggest removing it" → feedback_type: "suggestion"
- "Please use snake_case" → feedback_type: "requirement"
- "Also added a fix for..." → feedback_type: "information"
```

#### Pattern Recognition Guidelines
```
## Is Pattern (reusable across contexts):
Set to **true** if:
- Applies to multiple PRs/contexts
- General best practice or convention
- Recurring concern in MicroPython
- Teaching a principle, not fixing a specific bug

Set to **false** if:
- Specific to this PR's context
- One-time fix or adjustment
- Historical reference
- Merge/process comment

Examples:
- "avoid negation in #if" → is_pattern: true (applies broadly)
- "this specific config issue" → is_pattern: false (one-time)
- "Merged in abc123" → is_pattern: false (process)
```

#### Keywords Guidelines
```
## Keywords (2-5 technical terms):
Extract key nouns and concepts for text search:
- Function/module names mentioned
- Technical concepts (alignment, ISR, thread safety)
- Standards referenced (PEP 8, RTOS)
- Actions suggested (refactor, simplify, extract)

Format as JSON array: ["term1", "term2", "term3"]

Examples:
- Comment about macro safety → ["macro", "parenthesis", "side effects"]
- Comment about ISR context → ["ISR", "RTOS", "vTaskNotifyGive"]
- Comment about PEP 8 → ["PEP 8", "spacing", "keyword arguments"]
```

---

#### Example Categorizations

Include 5-10 examples from our validated samples:

```
# Example 1: Python style
Comment: "No spaces around "=" in keyword args."
→ {
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
}

# Example 2: ISR context
Comment: "Is this USB callback actually an ISR? Or should we instead be using `vTaskNotifyGive(mp_main_task_handle)` instead?"
→ {
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
}

# Example 3: Documentation
Comment: "Better to use `machine.idle()` here so it doesn't use power unnecessarily while waiting."
→ {
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
}
```

---

### Task 3: Update Database Storage

**File:** `categorize_headless.py` lines 240-280 (store_categorizations function)

**Changes:**
- Update INSERT statement to include all 13 fields
- Handle NULL values for port and subsystem
- Serialize keywords array to JSON

**New INSERT statement:**
```python
conn.execute("""
    INSERT OR REPLACE INTO comment_categories (
        comment_id, comment_type, domain_id, theme, severity,
        is_style_example, categorized_at,
        component, port, subsystem, language_context, code_construct,
        concern_type, feedback_type, is_pattern, cpython_related,
        has_code_suggestion, keywords
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    comment["id"],
    comment["type"],
    domain_id,
    cat["theme"],
    severity,
    1 if cat["is_style_example"] else 0,
    datetime.now().isoformat(),
    cat["component"],
    cat.get("port"),  # Can be None
    cat.get("subsystem"),  # Can be None
    cat["language_context"],
    cat["code_construct"],
    cat["concern_type"],
    cat["feedback_type"],
    1 if cat["is_pattern"] else 0,
    1 if cat["cpython_related"] else 0,
    1 if cat["has_code_suggestion"] else 0,
    json.dumps(cat["keywords"])
))
```

---

### Task 4: Update Validation

**File:** `categorize_headless.py` lines 280-310

**Changes:**
- Update required_fields list
- Add validation for new fields
- Handle nullable fields (port, subsystem)

```python
# Validate fields
required_fields = [
    "comment_num", "domain", "theme", "severity", "is_style_example",
    "component", "language_context", "code_construct", "concern_type",
    "feedback_type", "is_pattern", "cpython_related",
    "has_code_suggestion", "keywords"
]

if not all(field in result for field in required_fields):
    missing = [f for f in required_fields if f not in result]
    print(f"    Missing required fields: {missing}", file=sys.stderr)
    return None

# Validate keywords is an array with 2-5 items
if not isinstance(result["keywords"], list) or \
   len(result["keywords"]) < 2 or len(result["keywords"]) > 5:
    print(f"    Invalid keywords length: {len(result.get('keywords', []))}",
          file=sys.stderr)
    return None
```

---

### Task 5: Test and Validate

**Create test script:** `test_categorization.py`

```python
#!/usr/bin/env python3
"""
Test enhanced categorization on a small batch.
"""

import subprocess
import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "dpgeorge_reviews.db"

def test_batch():
    """Test categorization on 5 comments."""
    conn = sqlite3.connect(DB_PATH)

    # Get 5 uncategorized comments of different types
    test_comments = []

    # 1 Python comment
    cursor = conn.execute("""
        SELECT id FROM review_comments
        WHERE path LIKE '%.py' AND id NOT IN (
            SELECT comment_id FROM comment_categories
        )
        LIMIT 1
    """)
    if row := cursor.fetchone():
        test_comments.append(('review_comment', row[0]))

    # 1 C comment
    cursor = conn.execute("""
        SELECT id FROM review_comments
        WHERE path LIKE '%.c' AND id NOT IN (
            SELECT comment_id FROM comment_categories
        )
        LIMIT 1
    """)
    if row := cursor.fetchone():
        test_comments.append(('review_comment', row[0]))

    # 1 docs comment
    cursor = conn.execute("""
        SELECT id FROM review_comments
        WHERE path LIKE 'docs/%' AND id NOT IN (
            SELECT comment_id FROM comment_categories
        )
        LIMIT 1
    """)
    if row := cursor.fetchone():
        test_comments.append(('review_comment', row[0]))

    print(f"Testing on {len(test_comments)} comments...")

    # Mark them for testing (save IDs)
    with open('/tmp/test_comment_ids.json', 'w') as f:
        json.dump(test_comments, f)

    conn.close()

    print("\nRun: python3 scripts/categorize_headless.py")
    print("Then verify results with: python3 scripts/test_categorization.py --verify")

def verify_results():
    """Verify test categorizations."""
    with open('/tmp/test_comment_ids.json', 'r') as f:
        test_comments = json.load(f)

    conn = sqlite3.connect(DB_PATH)

    for comment_type, comment_id in test_comments:
        cursor = conn.execute("""
            SELECT
                theme, component, language_context, is_pattern,
                keywords, concern_type, feedback_type
            FROM comment_categories
            WHERE comment_id = ? AND comment_type = ?
        """, (comment_id, comment_type))

        row = cursor.fetchone()
        if row:
            print(f"\n✓ Comment {comment_id} ({comment_type}):")
            print(f"  Theme: {row[0]}")
            print(f"  Component: {row[1]}, Language: {row[2]}")
            print(f"  Pattern: {bool(row[3])}, Concern: {row[5]}")
            print(f"  Keywords: {row[4]}")
        else:
            print(f"\n✗ Comment {comment_id} NOT categorized")

    conn.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--verify':
        verify_results()
    else:
        test_batch()
```

---

## Implementation Sequence

### Step 1: Backup
```bash
cp scripts/categorize_headless.py scripts/categorize_headless.py.backup
```

### Step 2: Update Script
1. Update JSON schema (Task 1)
2. Enhance prompt (Task 2)
3. Update database storage (Task 3)
4. Update validation (Task 4)

### Step 3: Test
```bash
# Create test script
python3 scripts/test_categorization.py

# Run categorization on test batch
python3 scripts/categorize_headless.py

# Verify results
python3 scripts/test_categorization.py --verify
```

### Step 4: Consistency Check
```bash
# Run same batch twice, compare results
# Should have high consistency (>80% matching)
```

### Step 5: Full Run
```bash
# Clear test checkpoint
sqlite3 data/dpgeorge_reviews.db \
  "DELETE FROM sync_state WHERE key = 'categorize_headless_checkpoint'"

# Run full categorization
python3 scripts/categorize_headless.py
```

---

## Success Criteria

- ✓ Script runs without errors on test batch
- ✓ All 13 fields populated in database
- ✓ Keywords array has 2-5 items
- ✓ Port and subsystem can be NULL
- ✓ Consistency check: >80% agreement on repeated runs
- ✓ Query test: can find comments by component/language/pattern
- ✓ Full run completes within budget ($5) and time (2 hours)

---

## Risk Mitigation

**Risk 1: Schema mismatch**
- Mitigation: Test on 5 comments first
- Rollback: Restore from backup

**Risk 2: Haiku misunderstands enhanced fields**
- Mitigation: Include 5-10 examples in prompt
- Adjustment: Simplify field definitions if needed

**Risk 3: Budget exceeded**
- Mitigation: $5 hard limit in script
- Monitoring: Check cost after 100 batches

**Risk 4: Low consistency**
- Mitigation: Enhance prompt with clearer guidelines
- Acceptance: 70%+ consistency acceptable for initial run

---

## Estimated Effort

- **Update script:** 30 minutes
- **Test and validate:** 15 minutes
- **Full run:** 40-100 minutes
- **Verification:** 15 minutes

**Total: ~2-2.5 hours**

---

## Deliverables

1. Updated `categorize_headless.py` with 13-field schema
2. Test script `test_categorization.py`
3. Test results documentation
4. Full categorization results (22,805 comments)
5. Updated query examples with enhanced fields
