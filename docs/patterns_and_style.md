# dpgeorge Review Patterns and Style Guide

Based on analysis of 40 manually categorized samples from 22,805 total comments.

## Recurring Technical Patterns

These patterns appear consistently across different PRs and contexts. They represent dpgeorge's preferred approaches and common feedback themes.

### API Design Patterns

#### 1. Constructor Arguments with Sensible Defaults
**Example:** "Not sure that this is the best way to expose this configuration as a Python-level API. For this kind of thing the usual approach would be to use the WLAN constructor, eg: `wl = network.WLAN(reg_on=Pin(4), data_out=Pin(5), ..., freq=1_000_000)` And then have sensible defaults so it works on Pico 2 W with just `wl = network.WLAN()`."

**Context:** rp2 networking API design
**Principle:** Configuration should be in constructor with defaults, not separate setter methods.

#### 2. Descriptive Function Names
**Example:** "I think this function should be called `ssl_check_async_handshake_failure`. Is that what it's doing?"

**Context:** SSL/TLS async operations
**Principle:** Function names should clearly describe their purpose. Questions indicate name isn't self-explanatory.

#### 3. Use MicroPython Helper Functions
**Example:** "Changed to use `mp_obj_get_int_truncated()`."

**Context:** Type conversion in port code
**Principle:** Prefer MicroPython's abstraction functions over raw operations for consistency.

#### 4. Use HAL Abstractions
**Example:** "Please use `mp_hal_pin_config(pin_B0, MP_HAL_PIN_MODE_ANALOG, MP_HAL_PIN_PULL_NONE, 0)`."

**Context:** STM32 GPIO configuration
**Principle:** Use hardware abstraction layer instead of direct register access.

#### 5. Clarify Special Value Meanings
**Example:** "Perhaps the default here should be `DEFLATEIO_DEFAULT_WBITS`, and then the code that checks for `wbits==0` elsewhere in this file can be removed? Edit: or does `wbits=0` mean something special?"

**Context:** Default parameter values
**Principle:** Special values (0, -1, NULL) should have clear meaning or be avoided.

---

### Code Style Patterns

#### 6. Prefer bool Over int for Booleans
**Example:** "this can just be a `bool`"

**Context:** Flag variables
**Principle:** Use appropriate types - bool for true/false, not int.

#### 7. Avoid Negation in Conditionals
**Example:** "Better to not use negation and change the logic to `#if MICROPY_PY_BLUETOOTH_CYW43`."

**Context:** Preprocessor conditionals
**Principle:** Positive conditionals are clearer than negative ones.

#### 8. Avoid goto Statements
**Example:** "To avoid labels and goto (which is nice if possible) this function could be easily restructured so that it falls through to the bottom if there's an overflow, and the `mp_raise_msg` is at the bottom. Please try to do that."

**Context:** Error handling in py core
**Principle:** Prefer fall-through logic over goto/labels when feasible.

#### 9. Wrap Macro Arguments in Parentheses
**Example:** "Yes, good to always wrap macro args in parenthesis. Also, does this make any functional change? The macro arg `n` is now evaluated twice."

**Context:** C macro definitions
**Principle:** Parentheses prevent operator precedence issues. Watch for double evaluation side effects.

#### 10. Comment Intentionally Unused Values
**Example:** "I'd suggest: `reader.read_uint()  # bss size`"

**Context:** Discarding function return values
**Principle:** When intentionally ignoring a return value, comment what it represents.

#### 11. Extract Repeated Code to Helpers
**Example:** "Maybe create a small inline function that does this clock division setting? Because this code is repeated below in `machine_uart_init_helper`."

**Context:** Duplicated code in UART driver
**Principle:** DRY (Don't Repeat Yourself) - extract repeated logic.

---

### Portability Patterns

#### 12. Consider Struct Member Alignment
**Example:** "This could potentially be unaligned if `qstr_hash_t` is 1 byte and `qstr_len_t` is 2 bytes."

**Context:** Core qstr structure definition
**Principle:** Struct layout must work on all architectures. Alignment matters.

#### 13. Test Cross-Platform Behavior
**Example:** "Unfortunately this doesn't fully work on Linux: when running the test suite it uses `subprocess.check_output`, that's not a tty so it attempts the flush syscall, and fails with EINVAL..."

**Context:** Platform-specific file operations
**Principle:** Don't assume platform behavior. Test on multiple OSes.

---

### Testing Patterns

#### 14. Prefer Generic Tests Over Board-Specific
**Example:** "Thanks for the PR, but we are actually trying to move away from board-specific tests to more generic tests that work on all boards. So we won't be adding a specific 'hydrabus' target in the tests (you are welcome to keep it locally, of course)."

**Context:** Hardware test infrastructure
**Principle:** Tests should be portable. Board-specific tests fragment the test suite.

#### 15. Keep Tests Focused and Separated
**Example:** "Let's add that in a separate test."

**Context:** Multi-feature test file
**Principle:** One test per concern. Easier to debug and maintain.

#### 16. Ensure Comprehensive Test Coverage Before Merge
**Example:** "Agreed. I've now push some try-except-else(-finally) tests to master, rebased this on top of that, and added a test here for try-except-else-finally-break."

**Context:** Control flow edge cases
**Principle:** Blocking changes need comprehensive tests for all code paths.

---

### Documentation Patterns

#### 17. Provide Examples, Not Just Descriptions
**Example:** "The pin labelling is hard to get right. I think it'd be good to provide more info here, eg for a selection of boards what the format/style is for the pin names/numbers."

**Context:** Pin naming documentation
**Principle:** Concrete examples clarify abstract descriptions.

#### 18. Reference Shared Docs Instead of Duplicating
**Example:** "if this file is the same as for UM_FEATHERS2NEO, then you can just reference the other file, no need to duplicate it"

**Context:** Board deployment instructions
**Principle:** DRY applies to documentation too.

---

## Communication Style Characteristics

### Tone and Phrasing

#### Direct and Terse
```
"this can just be a `bool`"
"Strange that it needs this..."
"Ok!"
"fixed"
```
No unnecessary words. Gets straight to the point.

#### Question-Based Suggestions
```
"Is that what it's doing?"
"Or did you find information that says it won't work?"
"Maybe you need to compile with `-fno-common`?"
"Or does `wbits=0` mean something special?"
```
Questions invite discussion while suggesting alternatives.

#### Acknowledges Uncertainty
```
"I think it's possible to..."
"I guess the SAMD architecture..."
"Or possibly some flags (eg LTO) that interfere"
"although I could be wrong there"
```
Doesn't claim absolute certainty when uncertain.

#### Polite But Firm Requirements
```
"Please try to do that."
"Please use `mp_hal_pin_config(...)`."
"This still needs to be done..."
```
Clear about requirements, but polite phrasing.

#### Provides Rationale
```
"To avoid labels and goto (which is nice if possible)..."
"Because this code is repeated below in..."
"In that case it's not possible to make it return a const str."
```
Explains why changes matter, not just what to change.

#### Includes Code Examples
```python
wl = network.WLAN(reg_on=Pin(4), data_out=Pin(5), ..., freq=1_000_000)
```
```c
mp_hal_pin_config(pin_B0, MP_HAL_PIN_MODE_ANALOG, MP_HAL_PIN_PULL_NONE, 0)
```
```python
reader.read_uint()  # bss size
```
Shows concrete alternatives, not just abstract suggestions.

### Self-Correction and Understanding
```
"Ah, I see, I didn't appreciate that there could be a combined error message from the upper and lower parts of the error code. In that case it's not possible to make it return a const str. So I guess the overhead of `\"MBEDTLS_ERR_\"` is ok."
```
Acknowledges when he learns something or changes his view.

### Minimal Praise
```
"Ok!"
"Thanks!"
"Thank you!"
"Thanks, merged in..."
```
Acknowledgments are brief. Rare to see elaboration like "Great work!"

### Process Management
```
"OK, I'll concentrate on #18185 first."
"Yes, I'll do that as part of #17552."
"Closing for now. Feel free to reopen for further discussion."
```
Clear about priorities and decisions.

---

## Anti-Patterns (What to Avoid)

Based on blocking feedback:

### Memory and Safety Issues
- Struct alignment problems
- Memory leaks
- Uninitialized variables
- Buffer overflows
- NULL pointer dereferences

### Portability Problems
- Platform-specific assumptions
- Non-portable syscalls
- Compiler-specific behavior
- Endianness assumptions

### API Design Problems
- Unclear function names
- Missing defaults
- Inconsistent patterns
- Breaking changes without rationale

### Testing Gaps
- Incomplete test coverage
- Board-specific tests
- Missing edge case tests
- Tests that don't match implementation

---

## Examples by Severity

### Blocking (Must Fix Before Merge)
```
"Unfortunately this doesn't fully work on Linux..."
"This still needs to be done (describing delay and side-set)."
"This could potentially be unaligned if..."
"Agreed. I've now push some try-except-else(-finally) tests..."
```
**Characteristics:**
- Breaks functionality on some platforms
- Missing critical documentation
- Safety issues
- Incomplete test coverage

### Suggestions (Should Fix, Not Critical)
```
"Not sure that this is the best way to expose this configuration..."
"Maybe create a small inline function..."
"Better to not use negation and change the logic to..."
"To avoid labels and goto (which is nice if possible)..."
```
**Characteristics:**
- Better patterns available
- Code clarity improvements
- Maintainability enhancements
- Following project conventions

### Nitpicks (Minor Style Preferences)
```
"this can just be a `bool`"
"Reading this again, the word 'also' is out of place here."
```
**Characteristics:**
- Formatting preferences
- Minor wording improvements
- Type simplifications that don't affect behavior

---

## Application to AI-Assisted Reviews

When using this database for AI PR reviews:

### Search Strategy
1. **Match component/port/subsystem** - find precedents in same area
2. **Filter by concern_type** - target specific technical issues
3. **Prioritize patterns (is_pattern=true)** - apply general principles
4. **Reference style examples** - for phrasing feedback

### Writing Style Guidelines
1. **Be terse** - no fluff, get to the point
2. **Use questions** - "Is this handling X?" vs "This doesn't handle X"
3. **Provide code** - show, don't just tell
4. **Explain why** - give rationale for suggestions
5. **Acknowledge limits** - "I think" when uncertain
6. **Be polite but clear** - "Please" for requirements

### Avoid
1. Over-praising ("Great job!", "Excellent work!")
2. Verbose explanations
3. Apologetic tone ("Sorry but...")
4. Vague suggestions without specifics
5. Multiple exclamation marks
6. Emoji (never used by dpgeorge)

---

## Statistics Summary

From 40 samples:
- **42%** identified as reusable patterns
- **27.5%** good style examples
- **70%** suggestions (vs 13% blocking, 17% nitpick)
- **30%** include code examples
- **60%** technical feedback (vs 23% process, 17% questions)

This suggests dpgeorge's feedback is:
- Often reusable across contexts
- Primarily suggestive rather than blocking
- Frequently includes concrete code examples
- Focused on technical substance over process
