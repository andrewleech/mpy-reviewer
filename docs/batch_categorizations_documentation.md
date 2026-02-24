# Batch Categorizations: Documentation

5 samples from documentation reviews.

---

## DOC-1: Documentation structure/placement

**PR #16661:** docs: Note which ports have default or optional network.PPP support
**File:** docs/library/network.PPP.rst
**Comment:** "IMO this should be moved down after the main heading, after the first paragraph. Note that the first paragraph below already states 'only available on selected ports'."

**Categorization:**
```json
{
  "domain": "documentation",
  "theme": "documentation structure and placement",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "docs",
  "port": null,
  "subsystem": "networking",
  "language_context": "documentation",
  "code_construct": "documentation_page",
  "concern_type": "documentation",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": false,
  "keywords": ["structure", "placement", "heading", "organization"]
}
```

**Notes:** Pattern - avoid redundant information, place specifics after overview. References existing text to justify placement.

---

## DOC-2: Documentation completeness

**PR #7620:** manifest docs
**File:** docs/reference/manifest.rst
**Comment:** "Need to add the `freeze(...)` function name line before this paragraph."

**Categorization:**
```json
{
  "domain": "documentation",
  "theme": "missing function signature in documentation",
  "severity": "blocking",
  "is_style_example": false,
  "component": "docs",
  "port": null,
  "subsystem": null,
  "language_context": "documentation",
  "code_construct": "documentation_page",
  "concern_type": "documentation",
  "feedback_type": "requirement",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["function signature", "completeness", "freeze"]
}
```

**Notes:** Pattern - document function signatures before explaining them. Direct requirement.

---

## DOC-3: Provide full URLs in documentation

**PR #15942:** samd/ports: Update deploy instructions
**File:** ports/samd/boards/SAMD21_XPLAINED_PRO/deploy_xplained_pro.md
**Comment:** "I think it would be better if this URL was the full URL of the .hex file, like: `Get the bootloader from https://micropython.org/resources/firmware/bootloader-xplained-pro-v3.16.0-15-gaa52b22.hex`"

**Categorization:**
```json
{
  "domain": "documentation",
  "theme": "use full URLs for direct file access",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "docs",
  "port": "samd",
  "subsystem": "board_support",
  "language_context": "documentation",
  "code_construct": "documentation_page",
  "concern_type": "documentation",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["URL", "direct link", "usability", "deployment"]
}
```

**Notes:** Pattern - provide direct, complete URLs for downloads. Better user experience. Includes specific example.

---

## DOC-4: Code examples should follow best practices

**PR #16475:** docs/rp2: Add wlan information to the quickref
**File:** docs/rp2/quickref.rst
**Comment:** "Better to use `machine.idle()` here so it doesn't use power unnecessarily while waiting."

**Categorization:**
```json
{
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

**Notes:** Important pattern - documentation examples should show optimal approaches, not just working code. Teaches good habits.

---

## DOC-5: Documentation brevity and focus

**PR #5184:** ESP32 RMT Implementation
**File:** docs/esp32/quickref.rst
**Comment:** "This kind of historical language is better suited to the reference docs of `esp32.RMT` rather than a quick ref. For here I'd suggest something short and to the point like 'The RMT is esp32-specific and...'"

**Categorization:**
```json
{
  "domain": "documentation",
  "theme": "keep quick reference brief and focused",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "docs",
  "port": "esp32",
  "subsystem": "rmt",
  "language_context": "documentation",
  "code_construct": "documentation_page",
  "concern_type": "documentation",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["brevity", "quick reference", "focus", "historical"]
}
```

**Notes:** Pattern - distinguish between quick reference (brief, practical) and full reference (detailed, historical). Provides alternative phrasing.

---

## Summary of Documentation Batch

**Patterns identified (is_pattern=true): 5/5 (100%)**
1. Place specific details after overview, avoid redundancy
2. Always include function signatures before explanation
3. Provide full, direct URLs for downloads
4. Code examples should demonstrate best practices
5. Keep quick references brief, save detail for full reference

**Style examples (is_style_example=true): 4/5 (80%)**
- Consistently provides specific suggestions
- Uses "I think", "IMO", "better to"
- Gives concrete alternative text

**Coverage:**
- All domain: documentation
- Concerns: structure, completeness, usability, correctness, focus

**Severity:**
- Blocking: 1 (missing required information)
- Suggestion: 4

**Feedback types:**
- Suggestion: 4
- Requirement: 1

**Key insight:** Documentation patterns are highly consistent and reusable - all 5 are general principles applicable across all docs.
