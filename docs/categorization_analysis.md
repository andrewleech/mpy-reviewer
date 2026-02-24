# Categorization Analysis

## Current PR Labels (from micropython/micropython)

**Port-specific:**
- port-alif, port-cc3200, port-embed, port-esp32, port-esp8266, port-mimxrt
- port-nrf, port-powerpc, port-qemu, port-renesas-ra, port-rp2, port-samd
- port-stm32, port-unix, port-webassembly, port-windows, port-zephyr

**Component areas:**
- board-definition, drivers, examples, extmod, lib, docs, ports

**Change types:**
- bug, enhancement, proposed-close, needs-info

**Infrastructure:**
- github_actions, dependencies

## File Path Patterns

**Top-level directories by comment frequency:**
1. ports/ (2953 comments) - 43% of all comments
2. py/ (1030 comments) - 15%
3. extmod/ (734 comments) - 11%
4. docs/ (588 comments) - 9%
5. tests/ (495 comments) - 7%
6. tools/ (307 comments) - 4%

**Most commented files:**
- py/mpconfig.h (64) - configuration macros
- extmod/modbluetooth.c (59) - Bluetooth module
- py/objtype.c (46) - type system
- ports/mimxrt/Makefile (42) - build system
- ports/rp2/machine_uart.c (42) - UART driver

## Sample Comment Patterns

### 1. Type/Data Structure Comments
**Sample:** "this can just be a `bool`"
**Pattern:** Suggesting simpler/more appropriate data types
**Context:** Code optimization, clarity

### 2. Platform/Portability Comments
**Sample:** "Unfortunately this doesn't fully work on Linux: when running the test suite it uses `subprocess.check_output`, that's not a tty so it attempts the flush syscall, and fails with EINVAL"
**Pattern:** Cross-platform behavior issues
**Context:** Testing, portability concerns

### 3. Macro Safety Comments
**Sample:** "Yes, good to always wrap macro args in parenthesis. Also, does this make any functional change? The macro arg `n` is now evaluated twice."
**Pattern:** C macro best practices, side effects
**Context:** Code correctness, C language specifics

### 4. Documentation/Clarity Comments
**Sample:** "Reading this again, the word "also" is out of place here. I suggest 'In addition to the methods below, array objects also ...'."
**Pattern:** Documentation wording improvements
**Context:** User-facing documentation quality

### 5. Architecture/Design Comments
**Sample:** "Do you want to have the OPENMV_N6 board definition included in MicroPython's stm32 port (like with the OPENMV_AE3)? If so, it should work with mboot."
**Pattern:** Integration questions, design decisions
**Context:** Board support, architectural choices

### 6. Naming/API Design Comments
**Sample:** "I think this function should be called `ssl_check_async_handshake_failure`. Is that what it's doing?"
**Pattern:** Function naming clarity
**Context:** API design, code readability

### 7. Test Strategy Comments
**Sample:** "Let's add that in a separate test."
**Pattern:** Test organization decisions
**Context:** Test coverage, maintainability

### 8. Implementation Detail Comments
**Sample:** "Changed to use `mp_obj_get_int_truncated()`."
**Pattern:** Suggesting MicroPython-specific functions
**Context:** Codebase consistency, best practices

### 9. Alignment/Low-level Comments
**Sample:** "This could potentially be unaligned if `qstr_hash_t` is 1 byte and `qstr_len_t` is 2 bytes."
**Pattern:** Memory alignment concerns
**Context:** Portability, hardware compatibility

## Proposed Enhanced Categorization Schema

### Core Fields (existing)
- **domain**: Technical area (memory, performance, portability, etc.)
- **theme**: Specific issue or pattern
- **severity**: blocking | suggestion | nitpick
- **is_style_example**: Writing style quality indicator

### New Fields for Better Searchability

#### 1. Component Classification
- **component**: Which major codebase area
  - `py_core` - Core Python implementation
  - `extmod` - Extended modules
  - `port_specific` - Port-specific code
  - `drivers` - Hardware drivers
  - `tools` - Development tools
  - `tests` - Test suite
  - `docs` - Documentation
  - `build_system` - Makefiles, configuration
  - `examples` - Example code

- **port**: Affected port (if applicable)
  - `esp32`, `stm32`, `rp2`, `unix`, `generic`, etc.
  - NULL for port-agnostic comments

- **subsystem**: More specific subsystem
  - `bluetooth`, `networking`, `usb`, `filesystem`, `uart`, `i2c`, `spi`
  - `gc`, `vm`, `compiler`, `types`, `asyncio`, `ssl`, etc.

#### 2. Technical Context
- **language_context**: What language/format
  - `c_code`, `python_code`, `documentation`, `makefile`, `shell_script`, `yaml`

- **code_construct**: What's being discussed
  - `function`, `macro`, `struct`, `typedef`, `class`, `module`
  - `test_case`, `documentation_page`, `build_rule`, `config_option`

- **concern_type**: Nature of the feedback
  - `correctness` - Logic bugs, wrong behavior
  - `safety` - Memory safety, undefined behavior, alignment
  - `api_design` - Interface design, naming, signatures
  - `style` - Formatting, naming conventions
  - `performance` - Speed, efficiency
  - `portability` - Cross-platform compatibility
  - `maintainability` - Code clarity, organization
  - `testing` - Test coverage, test correctness
  - `documentation` - Docs completeness, clarity
  - `security` - Security vulnerabilities
  - `compatibility` - CPython compatibility, API stability

#### 3. Comment Characteristics
- **feedback_type**: How the comment is phrased
  - `question` - Asking for clarification
  - `suggestion` - Proposing improvement
  - `requirement` - Must change
  - `praise` - Positive feedback (rare!)
  - `information` - Providing context/explanation
  - `alternative` - Suggesting different approach

- **is_pattern**: Is this a recurring pattern/best practice?
  - `true` - Common pattern that applies broadly
  - `false` - Specific to this PR

- **cpython_related**: Mentions CPython compatibility?
  - `true` / `false`

- **has_code_suggestion**: Does comment include specific code?
  - `true` / `false`

#### 4. Keywords/Tags
- **keywords**: JSON array of relevant technical terms
  - Extract important nouns: function names, module names, concepts
  - Example: `["mp_obj_get_int_truncated", "type checking", "integer conversion"]`

## Benefits for Query/Search

When reviewing a new PR, we can search for relevant past comments by:

1. **By component**: "Show me comments on esp32 port UART drivers"
2. **By concern**: "Find memory safety issues in extmod"
3. **By pattern**: "Get recurring API design patterns"
4. **By subsystem**: "All Bluetooth-related feedback"
5. **By file type**: "C code macro safety comments"
6. **By feedback style**: "Show requirements vs suggestions"
7. **By keywords**: "Comments mentioning alignment or memory layout"
8. **By size/scope**: Filter by PR size to find relevant precedents

## Validation Results

**Status:** ✅ Schema validated on 40 diverse samples

### Sample Testing Summary

**Batch 1:** 10 review comments (manual categorization)
- All fields applicable
- Identified 7 recurring patterns
- 4 good style examples

**Batch 2:** 30 mixed comments (20 review + 10 issue)
- 100% success rate - all comments categorizable
- 17 total recurring patterns identified (42% of comments)
- 11 good style examples
- Schema handled edge cases well (merge comments, minimal comments, process comments)

### Field Performance

**Highly effective:**
- `component`, `port`, `subsystem` - clear location context
- `concern_type` - captured feedback nature better than domain alone
- `is_pattern` - identified reusable patterns (42% success rate)
- `feedback_type` - distinguished questions/suggestions/requirements effectively
- `keywords` - 2-5 technical terms provided good search dimensions

**Minor ambiguity:**
- `domain` vs `concern_type` - some overlap, but both useful
- `build_system` vs `portability` vs `architecture` - needs guidelines

**Appropriate NULL usage:**
- `subsystem` - NULL in 46% of general comments (correct)
- `port` - NULL for port-agnostic code (correct)

### Distribution Analysis

From 40 samples:

**Comment types:**
- Technical feedback: 60%
- Process/merge: 23%
- Questions/discussion: 17%

**Severity:**
- Suggestions: 70%
- Blocking: 13%
- Nitpicks: 17%

**Has code suggestions:** 30%
**Is pattern:** 42%
**Is style example:** 27.5%

## Schema Refinements

### Changes from initial proposal

1. **Added `feedback_type: "merge"`** - for merge confirmation comments
2. **Clarified NULL handling** - subsystem and port can be NULL appropriately
3. **Keywords guidelines** - 2-5 technical terms, focus on nouns (function names, concepts)

### Domain Disambiguation Guidelines

When choosing between overlapping domains:

**build_system vs portability:**
- Use `build_system` if about Make, compilation, flags, linker
- Use `portability` if about cross-platform code behavior

**architecture vs api_design:**
- Use `architecture` if about system structure, module organization
- Use `api_design` if about function signatures, naming, user-facing interfaces

**correctness vs safety:**
- Use `correctness` for logic bugs, wrong behavior
- Use `safety` for memory safety, alignment, undefined behavior

## Next Steps

1. ✅ Refine this schema based on more sample review
2. ✅ Test manual categorization on 20-30 diverse comments
3. ✅ Iterate on categories that are ambiguous or overlap too much
4. ⏳ Update database schema with new fields
5. ⏳ Build comprehensive prompt with examples for each field
6. ⏳ Test with claude -p on a batch of 20 comments
7. ⏳ Measure consistency (run same batch twice, compare)
8. ⏳ Finalize and run full categorization
