# Batch Categorizations: Port-Specific Patterns

10 samples from port-specific C code reviews (esp32, stm32, rp2).

---

## PORT-1: Control flow simplification

**PR #7779:** Implement STM32H73B3I_DK board
**File:** ports/stm32/usbd_conf.c
**Comment:** "instead of this guarded `else`, would be simpler to just put a `return;` at the end of the `USB_OTG_FS` if block"

**Categorization:**
```json
{
  "domain": "code_style",
  "theme": "simplify control flow with early return",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "port_specific",
  "port": "stm32",
  "subsystem": "usb",
  "language_context": "c_code",
  "code_construct": "function",
  "concern_type": "maintainability",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["early return", "control flow", "simplification", "else"]
}
```

**Notes:** Pattern - prefer early return over guarded else. Related to avoiding complex nesting.

---

## PORT-2: API consistency suggestion

**PR #8228:** ports/esp32: Add UM ESP32-S3 Boards
**File:** ports/esp32/boards/UM_PROS3/modules/pros3.py
**Comment:** "As above, maybe use `adc.read_uv()`?"

**Categorization:**
```json
{
  "domain": "api_design",
  "theme": "use consistent API across similar code",
  "severity": "suggestion",
  "is_style_example": false,
  "component": "port_specific",
  "port": "esp32",
  "subsystem": "adc",
  "language_context": "python_code",
  "code_construct": "function",
  "concern_type": "api_design",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["ADC", "API", "consistency", "read_uv"]
}
```

**Notes:** Pattern - use consistent API methods. References "as above" (assumes context).

---

## PORT-3: ISR context verification

**PR #12845:** esp32/usb: Wake main thread when usb receives data
**File:** ports/esp32/usb.c
**Comment:** "Is this USB callback actually an ISR? Or should we instead be using `vTaskNotifyGive(mp_main_task_handle)` instead?"

**Categorization:**
```json
{
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
  "keywords": ["ISR", "RTOS", "callback", "vTaskNotifyGive", "context"]
}
```

**Notes:** Important pattern - ISR context matters for RTOS calls. Questions and suggests alternative. Critical for embedded.

---

## PORT-4: Extract to helper function

**PR #12845:** esp32/usb: Wake main thread when usb receives data
**File:** ports/esp32/usb.c
**Comment:** "I think it would be good to put this in a function called `mp_hal_wake_main_task()`."

**Categorization:**
```json
{
  "domain": "api_design",
  "theme": "extract HAL helper function for reusability",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "port_specific",
  "port": "esp32",
  "subsystem": null,
  "language_context": "c_code",
  "code_construct": "function",
  "concern_type": "maintainability",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["HAL", "helper function", "mp_hal_", "extraction"]
}
```

**Notes:** Pattern - create HAL abstraction functions with mp_hal_ prefix. Provides specific name.

---

## PORT-5: Magic numbers to named constants

**PR #6501:** stm32/rfcore: Add WB55 wireless firmware updater
**File:** ports/stm32/boards/NUCLEO_WB55/rfcore_firmware.py
**Comment:** "perhaps make the registers (17/18) constants at the top of the file to easily change them (`_RTC_REG_STATE = const(18)` etc)"

**Categorization:**
```json
{
  "domain": "code_style",
  "theme": "replace magic numbers with named constants",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "port_specific",
  "port": "stm32",
  "subsystem": "board_support",
  "language_context": "python_code",
  "code_construct": "config",
  "concern_type": "maintainability",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["magic numbers", "constants", "const", "registers"]
}
```

**Notes:** Classic pattern - named constants for magic numbers. Provides example format. Uses MicroPython's `const()`.

---

## PORT-6: Avoid negation in conditionals

**PR #10739:** Add Bluetooth support to Pico W
**File:** ports/rp2/mpbthciport.c
**Comment:** "Better to not use negation and change the logic to `#if MICROPY_PY_BLUETOOTH_CYW43`."

**Categorization:**
```json
{
  "domain": "code_style",
  "theme": "avoid negation in preprocessor conditionals",
  "severity": "suggestion",
  "is_style_example": false,
  "component": "port_specific",
  "port": "rp2",
  "subsystem": "bluetooth",
  "language_context": "c_code",
  "code_construct": "macro",
  "concern_type": "maintainability",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["preprocessor", "conditional", "negation", "readability"]
}
```

**Notes:** Pattern already in batch 2 sample 3 (PY-3). Positive logic is clearer.

---

## PORT-7: Module file naming convention

**PR #3578:** ports/esp32 add support for the ulp
**File:** ports/esp32/Makefile
**Comment:** "Putting the ULP class in the esp32 module would mean this file becomes `esp32_ulp.c`."

**Categorization:**
```json
{
  "domain": "architecture",
  "theme": "file naming matches module structure",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "port_specific",
  "port": "esp32",
  "subsystem": null,
  "language_context": "c_code",
  "code_construct": "module",
  "concern_type": "maintainability",
  "feedback_type": "information",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["file naming", "module", "convention", "esp32_"]
}
```

**Notes:** Pattern - file names should reflect module structure (module_class.c). Explains consequence of design decision.

---

## PORT-8: Include dependencies

**PR #13096:** core,rp2,esp8266,windows, unix: Add new cross-port functions
**File:** ports/rp2/cyw43_configport.h
**Comment:** "this file now needs to include runtime.h, to get this function defn"

**Categorization:**
```json
{
  "domain": "correctness",
  "theme": "add missing include for function definition",
  "severity": "blocking",
  "is_style_example": false,
  "component": "port_specific",
  "port": "rp2",
  "subsystem": "networking",
  "language_context": "c_code",
  "code_construct": "include",
  "concern_type": "correctness",
  "feedback_type": "requirement",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["include", "header", "dependency", "function definition"]
}
```

**Notes:** Pattern - files must include headers for functions they use. Direct requirement.

---

## PORT-9: Array types and compiler compatibility

**PR #3945:** stm32/flashbdev.c: Bugfix
**File:** ports/stm32/flashbdev.c
**Comment:** "Zero length arrays may give problems with certain compilers. And probably they don't even need to be arrays, they could just be `uint8_t` the same as `_flash_fs_start` and `_flash_fs_end`"

**Categorization:**
```json
{
  "domain": "portability",
  "theme": "avoid zero-length arrays for compiler compatibility",
  "severity": "suggestion",
  "is_style_example": true,
  "component": "port_specific",
  "port": "stm32",
  "subsystem": "filesystem",
  "language_context": "c_code",
  "code_construct": "typedef",
  "concern_type": "portability",
  "feedback_type": "suggestion",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": true,
  "keywords": ["zero-length array", "compiler", "portability", "uint8_t"]
}
```

**Notes:** Pattern - avoid non-standard C (zero-length arrays). Suggests simpler alternative. Two points in one comment.

---

## PORT-10: Code formatting consistency

**PR #17971:** esp32: Update machine_i2c.c
**File:** ports/esp32/machine_i2c.c
**Comment:** "Please put this on one line to match surrounding code."

**Categorization:**
```json
{
  "domain": "code_style",
  "theme": "match surrounding code formatting",
  "severity": "nitpick",
  "is_style_example": true,
  "component": "port_specific",
  "port": "esp32",
  "subsystem": "i2c",
  "language_context": "c_code",
  "code_construct": "function",
  "concern_type": "style",
  "feedback_type": "requirement",
  "is_pattern": true,
  "cpython_related": false,
  "has_code_suggestion": false,
  "keywords": ["formatting", "consistency", "one line", "surrounding code"]
}
```

**Notes:** Pattern - match existing code style in the file. Direct requirement despite being stylistic.

---

## Summary of Port-Specific Batch

**Patterns identified (is_pattern=true): 10/10 (100%)**
1. Prefer early return over guarded else
2. Use consistent APIs across similar code
3. Verify ISR context and use appropriate RTOS primitives
4. Extract HAL helper functions (mp_hal_* prefix)
5. Replace magic numbers with named constants
6. Avoid negation in preprocessor conditionals
7. File naming should match module structure
8. Include headers for functions used
9. Avoid zero-length arrays (non-standard C)
10. Match surrounding code formatting

**Style examples (is_style_example=true): 8/10 (80%)**

**Coverage:**
- Code style: 3
- API design: 2
- Correctness: 2
- Portability: 1
- Architecture: 1
- All C code focused

**Severity:**
- Blocking: 2 (ISR context, missing include)
- Suggestion: 7
- Nitpick: 1

**Feedback types:**
- Suggestion: 7
- Requirement: 2
- Question: 1

**Key insight:** Port-specific code has very high pattern rate (100%) because embedded development has strict constraints and conventions. ISR context and RTOS primitives are critical concerns.
