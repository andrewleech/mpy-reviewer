# Batch Categorizations: Build System

5 samples from Makefile and build configuration reviews.

---

## BUILD-1: Remove unnecessary build configuration

**PR #17001:** rp2/boards: Add new Solder Party board
**File:** ports/rp2/boards/SOLDERPARTY_RP2350_STAMP_XL/mpconfigboard.cmake
**Comment:** "You don't need this if the manifest is the standard one (which it is for this board)."

**Categorization:**
```json
{
  "domain": "build_system",
  "theme": "remove unnecessary configuration when using defaults",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "port_specific",
  "port": "rp2",
  "subsystem": "board_support",
  "language_context": "cmake",
  "code_construct": "config",
  "concern_type": "maintainability",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": false,
  "keywords": ["unnecessary", "default", "manifest", "cleanup"]
}
```

**Notes:** Pattern - don't override defaults with the same value. Keep config minimal. Explains rationale.

---

## BUILD-2: Variable naming consistency

**PR #9072:** stm32/Makefile: Automatically rebuild if make MBOOT=0/1 changed
**File:** ports/stm32/Makefile
**Comment:** "I think this should be `USE_MBOOT`?"

**Categorization:**
```json
{
  "domain": "build_system",
  "theme": "consistent build variable naming",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "port_specific",
  "port": "stm32",
  "subsystem": null,
  "language_context": "makefile",
  "code_construct": "build_rule",
  "concern_type": "maintainability",
  "feedback_type": "question",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["variable naming", "MBOOT", "USE_", "consistency"]
}
```

**Notes:** Pattern - build variables should follow naming conventions (USE_* for boolean flags). Question form.

---

## BUILD-3: Question unnecessary configuration

**PR #15158:** ports/nrf: Consolidate stdio functions
**File:** ports/nrf/boards/PCA10056/mpconfigboard.mk
**Comment:** "Is this line needed, since jlink is the default flasher?"

**Categorization:**
```json
{
  "domain": "build_system",
  "theme": "question necessity of explicit default configuration",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "port_specific",
  "port": "nrf",
  "subsystem": "board_support",
  "language_context": "makefile",
  "code_construct": "config",
  "concern_type": "maintainability",
  "feedback_type": "question",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": false,
  "keywords": ["necessity", "default", "jlink", "flasher"]
}
```

**Notes:** Pattern - question lines that set defaults explicitly. Same principle as BUILD-1. Question form.

---

## BUILD-4: Minimal examples match reference implementation

**PR #16960:** py/py.mk: Enable makefile for USER_C_MODULES path
**File:** examples/usercmodule/user_c_modules.mk
**Comment:** "For this example, I'd suggest keeping it as minimal as possible, and similar to the cmake version. Eg just: `include cexample/micropython.mk` ..."

**Categorization:**
```json
{
  "domain": "documentation",
  "theme": "keep examples minimal and consistent with other implementations",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "examples",
  "port": null,
  "subsystem": null,
  "language_context": "makefile",
  "code_construct": "build_rule",
  "concern_type": "documentation",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["minimal", "example", "consistency", "cmake"]
}
```

**Notes:** Pattern - examples should be minimal and consistent across build systems (Make vs CMake). Provides specific suggestion.

---

## BUILD-5: Descriptive build option naming

**PR #9054:** stm32/isr: Add option to run flash & uart isr function from ram
**File:** ports/stm32/Makefile
**Comment:** "How about calling this option `MICROPY_HW_ENABLE_ISR_UART_FLASH_FUNCS_IN_RAM`?"

**Categorization:**
```json
{
  "domain": "build_system",
  "theme": "descriptive naming for build options",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "port_specific",
  "port": "stm32",
  "subsystem": null,
  "language_context": "makefile",
  "code_construct": "config",
  "concern_type": "api_design",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["naming", "MICROPY_HW_", "descriptive", "build option"]
}
```

**Notes:** Pattern - build options should be fully descriptive, follow naming conventions (MICROPY_HW_ENABLE_*). Provides specific alternative.

---

## Summary of Build System Batch

**Patterns identified (is_pattern=true): 5/5 (100%)**
1. Don't override defaults explicitly - keep config minimal
2. Use consistent naming conventions (USE_*, MICROPY_HW_ENABLE_*)
3. Question necessity of explicit defaults
4. Keep examples minimal and consistent across build systems
5. Build option names should be fully descriptive

**Style examples (is_style_example=true): 5/5 (100%)**
- Uses questions to encourage thinking ("Is this needed?", "How about...?")
- Provides specific alternative names
- Explains rationale ("since jlink is the default")

**Coverage:**
- Domain: build_system (4), documentation (1)
- All Makefile/CMake related

**Severity:**
- All suggestions (0 blocking)

**Feedback types:**
- Suggestion: 3
- Question: 2

**Key insight:** Build system feedback focuses heavily on minimalism and naming conventions. Questions are used to prompt removal of unnecessary config.
