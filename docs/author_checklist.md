# MicroPython PR Author Checklist

Auto-generated from ~19.5K categorized review comments by the lead maintainer. Each item represents a cluster of related review feedback, ranked by importance.

## Architecture

- [ ] **Place shared code in port directories instead of duplicating across boards; configure modules per board based on available memory constraints.**
  - MicroPython targets diverse hardware with varying resources. File organization and per-board module configuration prevent unnecessary duplication and allow the same codebase to work efficiently across different memory-constrained devices.
  - *Applies to:* C code in py/ and extmod/, architecture decisions across ports
  - *Frequency:* 582 (95 blocking, 482 suggestion, 5 nitpick)
  - Examples:
    - > Ok, yes, we'd then need #ifndef in mpconfigport.h for those options that are configurable.
    - > This will need to go in mp_reset(), so that when you press CTRL-D (soft reset) the script is run again.

- [ ] **Prefer single-file module implementations over package structures, and place generic drivers in the drivers/ directory with examples collocated in the code**
  - Single-file modules minimize import complexity and on-device storage overhead. Placing generic drivers in a central location with embedded examples makes the codebase more maintainable and discoverable.
  - *Applies to:* Driver implementations targeting micropython-lib or the drivers/ directory, and build system manifest files
  - *Frequency:* 29 (4 blocking, 25 suggestion)
  - Examples:
    - > This would be a candidate to put in `micropython-lib`.
    - > > There's no need to marry those 2 ways, a lot of effort will be wasted, and only a monster will ensue. Yes there is a need. The *entire point* of MicroPython is that it's *Python*.

- [ ] **Ensure uasyncio stream registration uses poller.modify() to handle simultaneous read/write operations as independent channels.**
  - uasyncio requires proper bidirectional stream handling where TX and RX channels are registered separately. Failing to use poller.modify() can cause race conditions or missed events on concurrent operations.
  - *Applies to:* extmod (uasyncio streams), py_core async features, port_specific UART drivers
  - *Frequency:* 14 (2 blocking, 12 suggestion)
  - Examples:
    - > Some alternatives with pros/cons relative to the approach in this PR: - Instead of making `uasyncio.Event.set()` soft-IRQ-safe, implement `loop.call_soon_threadsafe(func, args) as per CPython. This...
    - > > No, I don't mean removing anything, how such an idea could pop up based on the comment I wrote? Because you used the words "no need for", and "it can all be implemented within the scope of". > Wh...

## Portability

- [ ] **Use abstraction layers for platform-specific operations rather than direct HAL calls; keep enum values stable across different build configurations to maintain ABI compatibility.**
  - Direct HAL calls reduce portability across platforms and build variants. Stable enum values prevent binary incompatibility when code is compiled with different configuration options.
  - *Applies to:* Port-specific C code and hardware abstraction layers
  - *Frequency:* 339 (91 blocking, 245 suggestion, 3 nitpick)
  - Examples:
    - > You may be right that everything has M extension support, and probably also C. But at this stage (early stage for RISC-V lifetime) it's hard to tell and so I'd go conservative and spell it out as `...
    - > @stinos this doesn't seem to work, at least not for the Travis Windows build... Do some Windows env's use alloca.h, whilst others malloc.h? If so, is there a macro we can use to tell them apart?

## API Design

- [ ] **Use generic object extraction functions like mp_obj_get_array to accept both tuples and lists, and ensure disconnect/close events include required addressing information**
  - MicroPython APIs should be flexible about sequence types (lists vs tuples) and provide sufficient context in events for proper cleanup and debugging. This reduces API friction and improves compatibility.
  - *Applies to:* C APIs in extmod, port_specific drivers, and driver code handling collections and events
  - *Frequency:* 44 (2 blocking, 39 suggestion, 3 nitpick)
  - Examples:
    - > In e2ca8ab8fc2f824dc7ebaa8fe65c4d2e7891080e this was improved and you should now be able to return `dest[1] = MP_OBJ_SENTINEL` to continue lookup in `locals_dict`.
    - > For now, please don't implement `mode()` or `drive()` methods. They are not part of the core Pin API and the functionality of setting these values should be available via `init()`.

- [ ] **Use concise parameter names when context is clear and maintain consistent naming conventions across all ports for the same semantic parameter**
  - Short, consistent parameter names reduce confusion when porting code between different boards and make the API surface more discoverable. Inconsistency forces developers to check each port's documentation separately.
  - *Applies to:* Documentation and API definitions for port-specific modules, especially machine.Pin, machine.SPI, and machine.WLAN across all ports
  - *Frequency:* 29 (5 blocking, 23 suggestion, 1 nitpick)
  - Examples:
    - > This feels inconsistent with other machine APIs: if a method is acting like a getter and setter then the setter should take the value to set it to, which in this case would be 0, not `True`.
    - > I2C doesn't work with a stream interface because it's inherently a message based bus.

- [ ] **Avoid wrapper classes around core objects (e.g., Pin, LED); prefer direct use of standard library objects or simple functions**
  - Wrapper classes add unnecessary cognitive load and object overhead without providing meaningful abstraction. MicroPython's resource constraints and simplicity goals favor direct, minimal APIs.
  - *Applies to:* High-level API design in port_specific and driver code, particularly for hardware control (GPIO, LED, button) abstractions
  - *Frequency:* 27 (5 blocking, 21 suggestion, 1 nitpick)
  - Examples:
    - > As with the LED class I think it's much simpler to just do: ```python button = Pin(BUTTON, Pin.IN, Pin.PULL_UP) ``` and not have this class at all.
    - > Should the test run on import? It might get annoying to display the message on start up... especially since the only way to stop it running is to rebuild the firmware with this line removed. What i...

- [ ] **Maintain CPython compatibility for basic usage patterns and library structure; document and minimize lazy imports that trade IDE introspection for memory**
  - CPython compatibility allows code to run on both platforms with minimal changes, reducing maintainability burden. Lazy imports should be explicit and justified, as they break IDE code completion and discovery.
  - *Applies to:* Standard library implementations in py_core and extmod, particularly uasyncio, gc module, and public API entry points
  - *Frequency:* 24 (6 blocking, 17 suggestion, 1 nitpick)
  - Examples:
    - > I agree this makes things more consistent in uPy. At the very least, the change here does not make uPy more or less compatible with CPython, it just changes an existing non-CPy-compatible behaviour...
    - > Closing. As mentioned the goal is not to diverge too much with CPython, it makes writing code that runs on both uPy and CPy more difficult.

- [ ] **Use mp_obj_is_true for boolean conversion and maintain consistent parameter names (e.g., 'password' vs 'key') across all port implementations of the same interface**
  - mp_obj_is_true properly handles MicroPython's truthiness semantics. Consistent parameter naming across WLAN drivers (and other multi-port APIs) eliminates accidental incompatibilities when code switches boards.
  - *Applies to:* C API implementations in port_specific (especially machine.WLAN, machine.SPI) and extmod parameter extraction logic
  - *Frequency:* 24 (3 blocking, 21 suggestion)
  - Examples:
    - > > how could we make sure the interface can accommodate these future use cases? Have a look at how `esp_config()` does it (although that's a little more complex because it allows also to set paramet...
    - > The esp32 port uses the kw-arg `password` for the key, and kw-arg `authmod` for the security type. As with other things, best to keep these consistent across WLAN drivers (and cyw43 also uses `pass...

- [ ] **Verify API naming is consistent across all port implementations and changes do not break existing user code**
  - Users rely on consistent WLAN and power management API names across ESP32, STM32, and other ports for portable code. Breaking changes to established APIs prevent code portability between hardware platforms.
  - *Applies to:* Python APIs in extmod and port-specific network/power management modules
  - *Frequency:* 22 (3 blocking, 19 suggestion)
  - Examples:
    - > > it will still break user code How will it break user code if the old constants are left as they are? You could also update the network scripts to try `network.AUTH_xxx` first, and fall back to `n...
    - > > The idea was to support `config('hostname')` followed by `active(True)` On esp32 you need to run `active(True)` before `config(hostname=...)`, or it raises a `OSError: TCP/IP IF Not Ready` except...

- [ ] **Ensure version detection is available via MICROPY_VERSION macro and board configurations set final values (heap bounds, etc) directly without intermediate variables**
  - Third-party libraries need to detect the MicroPython version at build time, and board configs should specify final heap boundaries directly rather than through abstraction layers that obscure actual values.
  - *Applies to:* Board configuration headers, C code defining system constants, and mpconfigboard.h files
  - *Frequency:* 20 (4 blocking, 16 suggestion)
  - Examples:
    - > This is needed, eg, for 3rd party libraries to detect which MicroPython version they are building against.
    - > Instead of adding this (yet-another) config variable, how about instead the mpconfigboard.h file just sets `MICROPY_HEAP_START` and `MICROPY_HEAP_END` itself when it has SDRAM? So in those board co...

- [ ] **Ensure SSL/TLS and cryptographic APIs match CPython's exact signatures including both cafile and cadata parameters and compatible argument handling**
  - APIs named after CPython modules must have compatible signatures so users can write code that runs on both platforms without modification. Divergent signatures create portability barriers.
  - *Applies to:* SSL/TLS, cryptographic, and network security modules in extmod
  - *Frequency:* 16 (6 blocking, 9 suggestion, 1 nitpick)
  - Examples:
    - > @Carglglz sorry this hasn't received much attention lately. The blocker on this is how to get compatibility with CPython. If a module is named by the same name as a corresponding CPython module (in...
    - > CPython's signature of this method is: ```py SSLContext.load_cert_chain(certfile, keyfile=None, password=None) ``` But it looks like mbedtls requires both cert and key. So MicroPython's signature s...

- [ ] **Verify that unimplemented or unsupported methods raise exceptions consistently rather than returning stub values, and that configurable parameters like baudrate are not hardcoded to single values.**
  - Port-specific APIs must be explicit about what is not supported, and configuration parameters must allow user override for different hardware variants. Silent stubs mask missing functionality, while hardcoded values reduce driver portability.
  - *Applies to:* C code in port_specific drivers (UART, SPI, I2C, PWM)
  - *Frequency:* 18 (2 blocking, 16 suggestion)
  - Examples:
    - > This now raises.
    - > Unfortunately using `write1` here will be a breaking change, because it doesn't accept the additional arguments like `write` does. So, we'll need to use the same approach as you did with `stream_re...

- [ ] **Minimize API additions by using isinstance() checks for argument type detection instead of introducing new method parameters, and ensure new methods maintain backward compatibility with existing semantics.**
  - Python driver APIs grow quickly and become hard to document. Duck typing via isinstance() keeps the API surface smaller and more maintainable. New parameters or methods should align with existing conventions (e.g., if read() accepts a count argument, write() should too).
  - *Applies to:* Python drivers in drivers/ implementing SPI, I2C, or other communication protocols
  - *Frequency:* 16 (1 blocking, 15 suggestion)
  - Examples:
    - > As above, this would be `if self._use_i2c:`.
    - > > Then why read can have different arguments and semantics? True, spi.read() does allow a second argument. But at least its behaviour is still compatible with normal read (and I guess so would writ...

- [ ] **Use calibrated methods like read_uv() instead of raw ADC reads and maintain consistent public API methods across similar hardware interfaces**
  - Calibrated hardware interfaces provide portable APIs that drivers can override for extensibility, and consistency across port implementations reduces maintenance burden.
  - *Applies to:* Port-specific drivers and extmod code interfacing with ADC, neopixels, and other hardware sensors
  - *Frequency:* 12 (2 blocking, 10 suggestion)
  - Examples:
    - > As above, maybe use `adc.read_uv()`?
    - > IIRC this is part of the public API, to be able to override the `ORDER` (otherwise there's no way to support LEDs with a different ordering). See `esp32/modules/apa106.py`.

- [ ] **Allow users to explicitly mount SD cards in their boot.py or main.py rather than automatically mounting in the driver initialization**
  - Automatic hardware mounting reduces flexibility for users who may want conditional or deferred mounting, and explicit user control aligns with MicroPython's principle of explicit over implicit.
  - *Applies to:* Python drivers and extmod code providing SD card and storage interfaces
  - *Frequency:* 13 (13 suggestion)
  - Examples:
    - > > Do you ses supporting `spi=...` instead of supporting any of the SPI config on the `SDCard` constructor? In the case of the ESP32 using the SD-SPI implementation in the SDK we would need to extra...
    - > Does it make sense to automatically mount the SD card? It might be better to just leave it up to the user to mount it in their own `boot.py` or `main.py` when/if they want to use it (that's how som...

- [ ] **Expose all public constants in module locals dictionary and maintain consistent constant names across LAN and WLAN interfaces for portability**
  - Public constants must be defined in module dicts for user code to access them, and consistent naming across similar interfaces reduces API confusion and support burden.
  - *Applies to:* C code in extmod and port-specific WLAN, LAN, and network driver modules
  - *Frequency:* 11 (2 blocking, 9 suggestion)
  - Examples:
    - > As above, please remove.
    - > Wiznet is a LAN and shouldn't have these constants at all.

## Correctness

- [ ] **Avoid duplicating interrupt handler logic; return MP_EAGAIN on initial timeout for non-blocking operations; verify UART interrupt handler interaction with new read/write code.**
  - UART interrupt handlers are performance-critical and easy to break. Duplicate logic causes subtle race conditions, and incorrect timeout handling breaks non-blocking APIs.
  - *Applies to:* Port-specific UART and interrupt handling code
  - *Frequency:* 38 (28 blocking, 10 suggestion)
  - Examples:
    - > Thanks for the patch. Now I think about it, maybe also the `mp_machine_uart_read` function needs to be changed in the same way? UART interrupts are enabled for both RX and TX, but they are FIFO int...
    - > I'm pretty sure this will break the RXNE handler below because it'll read the current incoming data (from DR) and clear the RXNE flag. Probably best to cache the SR and DR values here, or similar. ...

- [ ] **Verify macro arguments are properly parenthesized and won't be misinterpreted due to type mismatches between call site and macro definition**
  - MicroPython macros frequently work with hardware types (DMA IDs, channel IDs, timeouts) where argument type confusion silently produces incorrect behavior. Unparenthesized arguments can also cause unintended multiple evaluations.
  - *Applies to:* C macros in port_specific and extmod directories, particularly for hardware abstraction (GPIO, DMA, timers)
  - *Frequency:* 31 (18 blocking, 12 suggestion, 1 nitpick)
  - Examples:
    - > But under what conditions would a bare-metal implementation return? The only choice seems to be on an IRQ, ie as soon as WFI returns. That's very inefficient, one should try to stay in this `poll_m...
    - > @tobbad this macro is now wrong (or it's called incorrectly) because the argument is a dma_id_t which is not a channel. So this macro will always evaluate to 0 for the F4/F7.

- [ ] **Replace os.system calls with subprocess.check_call and ensure asyncio coroutines handle CancelledError without suppressing task cancellations**
  - os.system is unsafe and deprecated; subprocess provides proper error handling. In asyncio, swallowing CancelledError can hide task cancellation bugs that would surface in CPython, making code harder to debug.
  - *Applies to:* Python code in extmod, py_core, and test suites that spawn subprocesses or handle async cancellation
  - *Frequency:* 26 (16 blocking, 10 suggestion)
  - Examples:
    - > > sorry if I came across unprofessionally You didn't, it's OK. > I really would like to help resolve this confusing issue We need to consider if this is an issue that is worth fixing, or if it's an...
    - > Does this now unintentionally suppress cancellations of tasks that wait on the server? Eg: ```python async def task(): srv = asyncio.start_server(...) srv.close() await srv.wait_closed() async def ...

- [ ] **Verify all alternative pin modes and feature guards use consistent preprocessor macros matching their C implementation definitions**
  - Mismatched or missing mode checks cause undefined behavior or silent failures on different hardware configurations. Pin mode guards must align with their corresponding usb/peripheral macro definitions.
  - *Applies to:* C code in port-specific drivers, GPIO configuration, and USB bootloader code
  - *Frequency:* 16 (11 blocking, 4 suggestion, 1 nitpick)
  - Examples:
    - > I think it should be `MICROPY_HW_USB_CDC` because that's what the `usb_usj_mode()` function is guarded with in `usb.c`.
    - > I think there needs to also be a check for `MP_HAL_PIN_MODE_ALT_OPEN_DRAIN` here.

- [ ] **Verify ISR context with appropriate RTOS primitives, use negative value checks instead of equality for sentinel detection, and ensure USB callbacks drain all buffered data before returning**
  - Incorrect ISR context or wrong synchronization primitives cause race conditions on RTOS systems. USB callbacks that exit with buffered data can silently drop incoming messages and cause protocol failures.
  - *Applies to:* Interrupt handlers, TinyUSB integration, FreeRTOS task synchronization, and ringbuffer drain logic
  - *Frequency:* 12 (11 blocking, 1 suggestion)
  - Examples:
    - > > which eventually traces back up to the top level TinyUSB task tud_task_ext() / tud_task() - so, no, it's an IRQ it's running directly from a separate FreeRTOS Task. So is it an IRQ, or is it runn...
    - > Is this USB callback actually an ISR? Or should we instead be using `vTaskNotifyGive(mp_main_task_handle)` instead?

- [ ] **Verify PWM and timer calculations handle integer overflow for large period values and maintain precision when converting to or from floating-point representations.**
  - PWM duty cycle calculations can silently overflow or lose precision with large timer periods (>2^31 or when converting 32-bit values to float), causing incorrect output at high duty cycles or duty cycle = 100%. Safe calculation requires overflow-aware arithmetic or order-of-operations changes.
  - *Applies to:* C code implementing PWM drivers and timer-based calculations in extmod/ and port_specific/
  - *Frequency:* 13 (9 blocking, 4 suggestion)
  - Examples:
    - > Hmm, it seems that this could overflow an int if the timer is 32-bit. Could use long long multiplication, or divide the period by 100 first if the period is larger than 2^31/100.
    - > Okay, so this is trickier than I first thought. If period is large then it'll lose precision converting to 32-bit float. This will be a problem if percent=100.0. Instead, probably need to do someth...

- [ ] **Verify soft reset properly clears heap state and that timeout/scheduling logic handles tick counter overflow with appropriate modulo operations and state checks.**
  - Soft reset must fully reinitialize the interpreter state to prevent stale heap references causing crashes or undefined behavior. Timeout logic using tick counters must wrap around cleanly when counters overflow, and scheduler state must be captured atomically to avoid race conditions.
  - *Applies to:* C code implementing soft reset, scheduling (mp_sched_schedule), and timeout logic in py_core/, port_specific/, and extmod/
  - *Frequency:* 11 (9 blocking, 2 suggestion)
  - Examples:
    - > in case the scheduler is full, this needs to be: ``` events_task_is_scheduled = mp_sched_schedule(...); ```
    - > I think this needs some &-logic to wrap it around.

- [ ] **Verify that interrupt-disabling functions respect the existing disable_irq context and don't disable interrupts if already disabled, and document all justifications for disabling RTC write protection with datasheet references.**
  - Nested interrupt disabling or disabling in a disable_irq context can cause unpredictable behavior and interrupt loss. RTC write protection disables are security-sensitive; justifications with datasheet references help reviewers understand the trade-off.
  - *Applies to:* C code in port_specific/ implementing low-level power management, RTC, and interrupt control
  - *Frequency:* 10 (9 blocking, 1 suggestion)
  - Examples:
    - > What if you enabled some wake up pins in code, to wake the MCU? Will that be disabled?
    - > If pyb.micros is going to be used in time critical Python code between disable_irq/enable_irq, then this function can't disable irq as well...

- [ ] **Do not wrap PRINT_REPR output in validation; use MICROPY_ERROR_PRINTER directly instead of snprintf with MP_ERROR_TEXT.**
  - PRINT_REPR output is already validated by the repr machinery. snprintf is incompatible with MP_ERROR_TEXT macro expansion, causing build failures or incorrect error output.
  - *Applies to:* C code in py_core (error handling), port_specific exception handling
  - *Frequency:* 10 (6 blocking, 4 suggestion)
  - Examples:
    - > CPython prints this message to stderr, so if we are aiming to match CPython (which I think is a good idea), this should be: ```c mp_obj_print_helper(MICROPY_ERROR_PRINTER, val, PRINT_STR); mp_print...
    - > snprintf won't work with `MP_ERROR_TEXT`. Just remove the `MP_ERROR_TEXT` macro.

- [ ] **Ensure stack pointer points one byte above the last valid byte (full descending stack); verify linker script alignment matches hardware memory layout.**
  - Stack pointer lifetime and alignment bugs cause silent memory corruption or RAM loss. Full descending stacks require precise pointer placement--off-by-one errors waste memory without obvious symptoms.
  - *Applies to:* Port-specific code (linker scripts, memory layout, startup code)
  - *Frequency:* 10 (5 blocking, 5 suggestion)
  - Examples:
    - > looks like the latter two variables here are unused
    - > @ryannathans why the "-1" here? The end of the stack should point to 1 byte above the last byte (the stack is full decending).

- [ ] **Verify ticks_cpu() counts CPU ticks (not microseconds) and handle counter overflow and race conditions in both the interrupt handler and read path**
  - MicroPython's timing functions must properly handle overflow and synchronization across interrupt contexts to prevent incorrect elapsed time calculations or data races when reading tick counters.
  - *Applies to:* C code in port-specific implementations and extmod dealing with timer/tick hardware abstractions
  - *Frequency:* 10 (5 blocking, 5 suggestion)
  - Examples:
    - > For `mp_hal_ticks_us()` (note us not ms) stm32 handles overflow both in the SysTick IRQ and in the call to `mp_hal_ticks_us()`. And SysTick IRQ runs at the highest priority. > Or, maybe agree that ...
    - > `ticks_cpu()` should count ticks of the CPU, not microseconds.

- [ ] **Verify NULL checks for socket protocol control blocks are in the correct logical order and prevent segmentation faults on dereferencing**
  - Socket operations must guard NULL checks before accessing pointers to avoid crashes, and the logic order matters when checking combined conditions.
  - *Applies to:* C code in extmod socket and network implementations
  - *Frequency:* 9 (6 blocking, 3 suggestion)
  - Examples:
    - > Can you please explain the logic behind this change? If pcb.tcp==NULL and one tries to write to the socket then it will seg fault right away.
    - > Shouldn't this be `(socket->pcb.tcp != NULL && ...`? Is it still writable if the pcb is NULL?

## Build System

- [ ] **Remove redundant configuration definitions; place board-level config in port-level files only; follow established macro patterns from existing port modules.**
  - Configuration duplication creates maintenance burden and inconsistency. Centralizing config in port files and following existing patterns reduces cognitive load and makes the codebase more maintainable.
  - *Applies to:* Build configuration files and port directories
  - *Frequency:* 82 (9 blocking, 69 suggestion, 4 nitpick)
  - Examples:
    - > This is already the default (in `py/mpconfig.h`), so can be removed.
    - > MICROPY_PY_BUILTINS_STR_HEX

- [ ] **Consolidate similar CI jobs (e.g., IDF v3/v4 builds) into single stages with clean steps; pin dependency versions (e.g., pyparsing) to avoid compatibility drift; use proper matrix configuration syntax.**
  - CI build time directly impacts developer productivity. Consolidating jobs and pinning versions reduces flakiness and maintenance burden. Correct matrix syntax prevents accidental job multiplication.
  - *Applies to:* CI/CD configuration files (GitHub Actions, Travis, etc.)
  - *Frequency:* 40 (7 blocking, 33 suggestion)
  - Examples:
    - > The number of jobs are growing, which means slower CI builds. Perhaps these two can be combined into one job? Would need a "make clean" in between building with gcc and clang. Also, the clang confi...
    - > There's no matrix in this Action file, so I don't think this will work as expected. It'll probably be just `esp32-` as the key, which is different to all the existing caches. I think you want to us...

- [ ] **Move large third-party libraries to git submodules rather than checking them into the repository directly, and verify any submodule updates are merged and stable in the upstream dependency before updating references.**
  - Checking in large third-party code bloats the repository, complicates licensing attribution, and makes updates harder to track. Submodules keep the main repo lean and make it clear when third-party code has been updated.
  - *Applies to:* Build system configuration and third-party library integration in port_specific/ (STM32Lib, CMSIS, Pico SDK)
  - *Frequency:* 14 (3 blocking, 11 suggestion)
  - Examples:
    - > > I changed submodulelib/stm32ilb to my fork temporary, but I posted a pull request > [micropython/stm32lib#21](https://github.com/micropython/stm32lib/pull/21) . > If this pull request is merged, ...
    - > > Does this PR depend on that pico-sdk being merged and then the pico-sdk submodule updated here to pull it in? Yes it does. Without it the build for this board fails because it cannot find `seeed_...

- [ ] **Place all generated files in the $(BUILD)/ directory and ensure the build process does not require internet connectivity**
  - Separating generated artifacts from source keeps the repository clean and portable, and offline builds are critical for CI/CD reliability and embedded development environments.
  - *Applies to:* Makefiles and build configuration in all port-specific builds and the main build system
  - *Frequency:* 11 (3 blocking, 8 suggestion)
  - Examples:
    - > Can _frozen_upip.c go in the $(BUILD)/ directory? Would be cleaner that way (since it's a generated file).
    - > This is no good, since now the standard unix build requires internet connectivity (and wget). I'm strongly -1 on that. See eg Travis failure.

## Documentation

- [ ] **Include MIT license header in all new C files; verify copyright attribution matches the file author; document license origin for vendored code.**
  - MicroPython enforces MIT licensing for legal compliance. Missing or incorrect headers create ambiguity about code provenance and complicate future licensing audits.
  - *Applies to:* All new C code files and imported third-party code
  - *Frequency:* 72 (13 blocking, 47 suggestion, 12 nitpick)
  - Examples:
    - > Maybe this should be your copyright instead, if you authored this entire file yourself?
    - > Does this file have any copyright/license? I see it originally came from PuTTY.

- [ ] **Format all code blocks with correct indentation, shell prompts (bash style with `$` or `>`), and format options/shortcuts as structured lists**
  - Proper documentation formatting makes examples copy-paste-able and easier to follow, reducing confusion for new users learning mpremote and other tools.
  - *Applies to:* Documentation files (RST format), tool guides, and code examples
  - *Frequency:* 21 (2 blocking, 15 suggestion, 4 nitpick)
  - Examples:
    - > this is bash style (also the ones below)
    - > this still needs to be done

- [ ] **Ensure all PIO instruction names are lowercase and instruction syntax documentation includes delay and side-set modifiers with proper formatting.**
  - PIO documentation must be precise and consistent to prevent user errors when writing assembly-like code. Lowercase names and complete modifier coverage ensure the documentation matches the actual syntax users will write.
  - *Applies to:* Documentation for Raspberry Pi Pico PIO instruction reference
  - *Frequency:* 15 (6 blocking, 9 suggestion)
  - Examples:
    - > Also need to add here the delay and side-set modifiers.
    - > these all need to be lower case: x, y, isr, osr. also it's `in_` to not clash with the `in` keyword

- [ ] **Add clarifying comments above critical control-flow sections and expand API documentation with hardware peripheral examples rather than external links.**
  - Critical sections benefit from inline documentation to guide future maintainers, and hardware examples in documentation ensure users can reference the documentation offline and understand context-specific behavior.
  - *Applies to:* Documentation and C code comments in all modules, especially for non-obvious initialization or configuration sequences
  - *Frequency:* 19 (3 blocking, 11 suggestion, 5 nitpick)
  - Examples:
    - > This extra constants bit is only needed if the module wants to export constants for the parser to fold (optimise). For this minimal port/minimal example I think it's simpler to just remove this bit.
    - > these are actually passes 2, 3 and 4 (stack size, code size, and emit, respectively) note that for inline-assembler code there are 3 passes (scope, code size, emit) but for normal Python functions ...

- [ ] **Verify documentation accurately describes MicroPython behavior, not CPython; mark any CPython-specific details as such.**
  - MicroPython documentation must reflect actual implementation differences from CPython to prevent user confusion and broken code. Incorrect descriptions mislead users into writing non-portable code.
  - *Applies to:* All documentation files (docs/library/, docs/reference/)
  - *Frequency:* 19 (2 blocking, 7 suggestion, 10 nitpick)
  - Examples:
    - > and this function should go in the integer section
    - > This second sentence is not true in MicroPython, so please remove it.

- [ ] **Remove explanations of obvious functionality; add articles ('a', 'the') before nouns; clarify phrasing to directly connect actions to outcomes.**
  - Documentation should avoid redundant explanations that waste space and insult reader intelligence. Proper grammar and clear phrasing make docs more accessible and professional.
  - *Applies to:* Documentation files (docs/library/, docs/reference/)
  - *Frequency:* 17 (2 blocking, 6 suggestion, 9 nitpick)
  - Examples:
    - > "... on the networking ..."
    - > This needs to be updated to state that more ports support `stations`. Maybe something like "some network interfaces in AP mode support the `stations` parameter which returns a list of connected STA...

- [ ] **Place module documentation in correct directory (e.g., docs/library/); document auto-generated constants from build scripts; use practical, simple code examples.**
  - Documentation structure must match library hierarchy for users to find content. Auto-generated constants must be documented or users cannot reference them. Practical examples are more useful than theoretical edge cases.
  - *Applies to:* Documentation files, hardware-specific documentation (stm, esp32, rp2)
  - *Frequency:* 13 (1 blocking, 12 suggestion)
  - Examples:
    - > Add a sentence like this: "Accessing peripheral registers requires a base address of the peripheral, eg `GPIOA`, plus the offset of the register to read/write, eg `GPIO_BSRR`. Combined it would be ...
    - > This file should be called `docs/library/stm.rst` and be linked from `docs/library/index.rst` under "Libraries specific to the pyboard" section. This file should also just be about this `stm` modul...

## Performance

- [ ] **Use MP_OBJ_NEW_SMALL_INT() for integer values fitting the small-int range instead of mp_obj_new_int(); avoid heap allocation in hot paths.**
  - Small-int fast paths eliminate unnecessary heap allocation and garbage collection pressure, improving performance and reducing memory fragmentation on resource-constrained systems.
  - *Applies to:* C code in py_core and extmod handling integer operations and conversions
  - *Frequency:* 76 (10 blocking, 64 suggestion, 2 nitpick)
  - Examples:
    - > I updated this PR to slightly optimise for code size, by reordering elements in the compiler's struct, which helps on some archs like x86 (the compiler's struct is rather large and accessing elemen...
    - > Using `mp_obj_new_int()` can lead to heap allocation and so will be slower than using `MP_OBJ_NEW_SMALL_INT()`. Also, this new formula here (the masking) will no longer work with `ticks_diff()`.

- [ ] **Run performance benchmarks on target hardware before and after changes to verify no regressions in common use cases**
  - Resource-constrained devices like Pico are sensitive to performance changes. Even optimizations for edge cases can inadvertently hurt common paths, especially in asyncio and event scheduling where microseconds matter.
  - *Applies to:* Python code in py_core, extmod, and test suites involving performance-sensitive operations
  - *Frequency:* 24 (2 blocking, 21 suggestion, 1 nitpick)
  - Examples:
    - > Running the performance benchmarks on a Pico board before and after this PR gives: ``` diff of scores (higher is better) N=100 M=100 perf0 -> perf1 diff diff% (error%) bm_chaos.py 210.70 -> 213.40 ...
    - > Not sure if this is the right fix. It will impact performance for a very uncommon case. I'd really like to get a test case that triggers this problem, then see how to fix it.

- [ ] **Cache qstr extraction results to avoid redundant lookups and remove unnecessary redundant checks that compiler optimization can eliminate**
  - Even small performance improvements accumulate significantly on resource-constrained devices. Some apparent safety guards become unnecessary after compiler optimization and should be removed to avoid double-checking.
  - *Applies to:* C code in py_core, particularly attribute lookup, string operations, and __getattr__ paths
  - *Frequency:* 21 (2 blocking, 17 suggestion, 2 nitpick)
  - Examples:
    - > This NLR is not needed, it's expensive and the GC will reclaim the memory (and it'll be rare that the code below raises).
    - > For user defined types (instances) the `locals_dict` will now be searched twice if something is not found: once in the custom `mp_obj_instance_attr` and then a second time here. I don't know if thi...

- [ ] **Avoid unnecessary allocations in performance-critical paths (e.g., pixel setters); optimize zero-write cases to skip buffer copies; use early returns to skip memoryview creation.**
  - MicroPython targets memory-constrained devices where unnecessary allocations cause GC pressure and latency spikes. Optimizing hot paths reduces power consumption and improves responsiveness.
  - *Applies to:* Driver code (neopixel, display), extmod performance-sensitive modules
  - *Frequency:* 14 (13 suggestion, 1 nitpick)
  - Examples:
    - > Eventually the compiler will be good enough such that the tuples can be true constant objects, but that's not currently the case.
    - > This seems like a lot of overhead just to set a single pixel. Here you need to allocate a generator function (which itself makes a copy of self.ORDER), then make a temporary bytes object, and also ...

- [ ] **Cache loop-invariant expressions outside loops and use uint32_t with mp_hal_ticks_ms for timeout tracking to avoid LTO optimization issues**
  - Link-time optimization can eliminate redundant computations, and efficient polling patterns prevent unnecessary state modifications that could be optimized away by the compiler.
  - *Applies to:* C code in port-specific and extmod modules with performance-critical polling or timeout logic
  - *Frequency:* 13 (1 blocking, 11 suggestion, 1 nitpick)
  - Examples:
    - > would it be better (doesn't modify any state, is faster to execute) to use: ``` if ((flags & MP_STREAM_POLL_RD) && (uart_is_readable(self->uart) || ringbuf_avail(&self->read_buffer) > 0)) { ``` ?
    - > Now that there's a `tud_cdc_rx_cb` function, the `tud_cdc_rx_wanted_cb` can be removed and its functionality moved into `tud_cdc_rx_cb` (otherwise there will be two passes over all incoming data). ...

## Memory

- [ ] **Analyze code size impact across all port builds (bare-arm, x86, stm32, unix variants); document any significant increases and justify the trade-off.**
  - ROM budget is critical on embedded systems. The lead maintainer tracks code size across diverse targets to prevent creeping bloat that breaks memory-constrained ports.
  - *Applies to:* C code changes in py_core and changes affecting multiple ports
  - *Frequency:* 56 (13 blocking, 40 suggestion, 3 nitpick)
  - Examples:
    - > Thanks for rebasing. Code size change for this PR is: ``` bare-arm: +120 +0.181% minimal x86: +256 +0.173% unix x64: +256 +0.051% unix nanbox: +320 +0.072% stm32: +100 +0.026% PYBV10 cc3200: +128 +...
    - > It looks like code size has increased, is that true for all/most builds? An exception like this is not normally in the flow of a working script (scripts do sometimes handle ImportError in their flo...

- [ ] **Optimize qstr storage by stripping redundant path prefixes and prefixing internal constants with underscore to reduce RAM footprint in .mpy files**
  - Unnecessary qstr entries inflate compiled bytecode and consume scarce RAM during initialization. Private/internal constants should be marked with underscore to signal they should not be exported.
  - *Applies to:* Module-level constants and imports in extmod and py_core, especially those processed by mpy-cross
  - *Frequency:* 25 (3 blocking, 22 suggestion)
  - Examples:
    - > > Isn't that a rather small overhead (in terms of performance I mean, or are we talking about some other overhead here?). In terms of performance, it'd just be at import time, requiring an extra le...
    - > Why are these added here, don't they increase the size of ports that don't use these qstrs? Eg bare-arm and minimal.

- [ ] **Verify structs are tightly packed with reordered fields, frequently-allocated objects are minimized in size, and no memory allocation occurs in interrupt handlers**
  - Embedded memory pressure is severe; inefficient struct packing wastes limited ROM/RAM across thousands of instances, and allocating in interrupt handlers causes deadlocks or memory exhaustion.
  - *Applies to:* C struct definitions in port-specific drivers, ringbuffer implementations, and interrupt handler code
  - *Frequency:* 15 (7 blocking, 8 suggestion)
  - Examples:
    - > now that this struct is mutable (ie not `const`) it probably makes sense to just have this as a `machine_hard_uart_buf_t buf` (ie not a pointer to a buf)
    - > This won't work because the objects below are defined "const" (to not use RAM, they live in ROM). Best way to deal with it is to have a separate non-const array to hold just the timeouts (the mutab...

- [ ] **Use m_new/m_del for allocations instead of gc_alloc/gc_free, and ensure all pointers passed to external functions or stored non-locally are either stack-allocated or in GC-scanned memory.**
  - m_new/m_del integrate with MicroPython's memory pool and are safer than raw gc_alloc. Passing pointers to external libraries risks dangling references if the GC cannot scan them, causing crashes or undefined behavior on the next collection cycle.
  - *Applies to:* C code in py_core/, extmod/, and port_specific/ that allocates memory or calls external libraries
  - *Frequency:* 15 (2 blocking, 13 suggestion)
  - Examples:
    - > You can simplify the code here and not have any temporary memory by the following: ```c mp_obj_tuple_t *tuple = MP_OBJ_TO_PTR(mp_obj_new_tuple(interps->len, NULL)); for (size_t i = 0; i < interps->...
    - > I think this is a dangerous use of malloc: we don't know where the pointer to arg is stored when you pass it to espconn_gethostbyname, so we don't know if the GC will scan it or not. Best probably ...

- [ ] **Optimize GC allocation strategies using block pointers or root references instead of heap allocation to reduce memory fragmentation and ISR-unsafe allocations**
  - Heap allocations in interrupt contexts or during GC operations can cause deadlocks or memory corruption, and proper GC allocation patterns reduce runtime overhead.
  - *Applies to:* C code in py_core and port-specific memory management and garbage collection
  - *Frequency:* 12 (1 blocking, 11 suggestion)
  - Examples:
    - > > I assume it's guaranteed `gc_alloc` returns zeroized memory? Yes, it is, but that's only because `MICROPY_GC_CONSERVATIVE_CLEAR` is always enabled. In the case that's not enabled, these fields wo...
    - > At the moment `MICROPY_BYTES_PER_GC_BLOCK` is a fixed constant. So I don't think we should change anything until that becomes a variable per area.

## Code Style

- [ ] **Use STATIC qualifier for file-scoped functions; maintain single blank lines only between code blocks; start error messages with lowercase letters.**
  - Consistent style reduces cognitive load during review and maintenance. STATIC limits symbol scope, preventing accidental cross-file dependencies. Lowercase error messages match Python convention.
  - *Applies to:* All C code files
  - *Frequency:* 71 (3 blocking, 36 suggestion, 32 nitpick)
  - Examples:
    - > As above, this call can go on one line.
    - > This looks unused.

- [ ] **Remove all unused imports, add const() declarations for module-level constants, and include proper license headers in new files**
  - Unused imports bloat code and confuse readers, const() declarations help MicroPython optimize constants to ROM, and license headers ensure compliance with project licensing requirements.
  - *Applies to:* All Python code files, especially new driver files and utility modules
  - *Frequency:* 22 (4 blocking, 8 suggestion, 10 nitpick)
  - Examples:
    - > `micropython` and `uctypes` are never used, so remove their import.
    - > please add `from micropython import const`

- [ ] **Squash related commits into logical units (e.g., all board URL additions into one commit) and ensure all commits use a real email address associated with the contributor.**
  - Clean commit history aids code archaeology and bisecting regressions. Real email addresses enable future contact about licensing questions and code ownership, which is a project requirement for contribution tracking.
  - *Applies to:* All pull requests with multiple commits, especially refactoring or documentation additions
  - *Frequency:* 14 (4 blocking, 9 suggestion, 1 nitpick)
  - Examples:
    - > Thanks, this is a nice clean up! There are lots of commits in this PR, I'd probably squash a few of them, eg the ones adding URLs for Nucleo boards. Actually, arguably the whole lot can be squashed...
    - > Thanks for the contribution, it looks good. But we usually require that contributions are made with an email address that is associated with the contributor themselves, to make it possible to conta...

- [ ] **Use correct plural spelling (e.g., 'buses' not 'bus') and maintain consistent grammar and article usage throughout.**
  - Inconsistent grammar and spelling in documentation reduces readability and appears unprofessional. Consistency across all docs is essential for user trust and clarity.
  - *Applies to:* Documentation files, comments in extmod and tools
  - *Frequency:* 32 (1 suggestion, 31 nitpick)
  - Examples:
    - > board
    - > For this copyright line, please use either your name or Arduino company name (not "MicroPython").

- [ ] **Remove all commented-out code and incomplete comments; omit config #define blocks when values match firmware defaults.**
  - Dead code clutter reduces maintainability and makes diffs harder to review. Default config values should not be explicitly defined—they add noise without semantic value.
  - *Applies to:* C code in port_specific (hardware ports, linker scripts, config headers)
  - *Frequency:* 19 (10 suggestion, 9 nitpick)
  - Examples:
    - > Please indent/format like the other lines.
    - > To keep the namespaces separated, please use `MICROPY_HW_RCC_xxx`.

- [ ] **Keep cosmetic changes in separate PRs and remove redundant preprocessor conditions to maintain PR focus on functional correctness**
  - Mixed cosmetic and functional changes obscure the actual logic modifications, making review and regression tracking harder.
  - *Applies to:* All C code in port-specific implementations
  - *Frequency:* 17 (9 suggestion, 8 nitpick)
  - Examples:
    - > Cosmetic.
    - > Please, no cosmetic changes in this PR, just functional ones related to the F429.

- [ ] **Consolidate duplicate preprocessor conditional blocks by extracting common code into macros or shared functions to reduce maintenance burden**
  - Duplicated conditional code increases bug risk and maintenance cost; consolidation via macros maintains clarity while reducing lines of code.
  - *Applies to:* C code in port-specific implementations, especially multi-variant ports like STM32
  - *Frequency:* 14 (11 suggestion, 3 nitpick)
  - Examples:
    - > Can this TODO and the commented-out code be removed?
    - > Because there's a bit of duplicated code here (the loop and timeout check), it might be cleaner to define a macro for the bits that differ, eg: ```c #if defined(STM32H7) #define ETH_SOFT_RESET(eth)...

## Testing

- [ ] **Confirm testing on actual hardware; provide minimal reproduction examples for reported issues; ensure all CI builds pass before requesting review.**
  - Hardware testing catches platform-specific bugs that unit tests miss. CI failures block merges and indicate incomplete validation. Clear test cases help maintainers verify the fix works.
  - *Applies to:* All PRs with hardware-dependent changes or bug fixes
  - *Frequency:* 70 (15 blocking, 54 suggestion, 1 nitpick)
  - Examples:
    - > Thanks, this looks good to me. Did you get a chance to test it?
    - > Thanks. It looks ok, but do you have a test case that demonstrates why it should be changed?

- [ ] **Preserve informative SKIP messages for platform-unsupported tests; extract generic test cases into shared test files usable across all ports.**
  - SKIP messages guide future port developers on missing functionality. Generic test cases shared across ports reduce duplication and ensure consistent behavior across hardware platforms.
  - *Applies to:* tests/ directory, port_specific test configuration
  - *Frequency:* 14 (14 suggestion)
  - Examples:
    - > I suggest keeping this line as `print("Please add support for this test on this platform.")`, because the test should not really be skipped on boards that do support this feature.
    - > Ok, that's great you can test these subtle conditions. Does it make sense to put these tests in to this repo, somehow? If they are generic `machine.UART` tests then they could be used to test any p...

## Error Handling

- [ ] **Return specific errno constants (e.g., -EIO, -EINVAL) rather than generic -1, and provide meaningful source names in error contexts**
  - Specific error codes allow callers to distinguish different failure modes and handle them appropriately. Generic -1 values and missing source context make debugging hardware integration issues significantly harder.
  - *Applies to:* C error handling in port_specific, extmod, and py_core, especially stream and I/O operations
  - *Frequency:* 31 (7 blocking, 24 suggestion)
  - Examples:
    - > it should return a negative errno value (ie `MP_OBJ_NEW_SMALL_INT(-EIO)`) instead of raising an exception
    - > MP_QSTR_ is passed here as the source name. Is this for a reason? It will lead to hard-to-find errors, without the filename given.

---

*60 items across 11 domains. Generated from 2334 review comment clusters.*