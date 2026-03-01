# Issue Triage Test Report

Generated: 2026-03-01T12:02:14.397695

**Issues tested:** 5

## Issue #12 (cloned from #18868)

**Title:** [TRIAGE TEST #18868] tests: cmdline/repl_lock.py and repl_cont.py intermittent failures

**Original Labels:** (none)

**Prompt length:** 9,010 chars

### Similar Issues (9 total)

| # | Title | State | RRF Score |
|---|-------|-------|-----------|
| 18867 | tests: thread stress tests intermittent failures under QEMU (stress_aes, stress_ | open | 0.0323 |
| 18866 | tests: thread/thread_gc1.py intermittent failure on CI | open | 0.0317 |
| 18870 | tests: thread/stress_heap.py intermittent failure on macOS | open | 0.0310 |
| 18869 | tests: extmod/time_time_ns.py intermittent failure due to CI runner clock precis | open | 0.0277 |
| 17540 | Undefined behavior with %q format specifier on LP64 and I16LP32 targets | open | 0.0258 |

### Duplicate Candidates

| # | Title | State | RRF Score |
|---|-------|-------|-----------|
| 6922 | Tests failing on current code, with CPython 3.9.1 | closed | 0.0340 |
| 18867 | tests: thread stress tests intermittent failures under QEMU (stress_aes, stress_ | open | 0.0318 |
| 18866 | tests: thread/thread_gc1.py intermittent failure on CI | open | 0.0313 |

### Related Reviews (5 total)

- **PR #8526** (testing): I haven't seen `repl_inspect` fail before (at least randomly fail).  The error diff from the CI is: ```diff --- /Users/runner/work/micropython/micro
- **PR #15937** (correctness): The CI shows the following failures: - Cortex-A9 has issue with some native tests, perhaps the ARM (non-Thumb) emitter has some bugs? - On RISC-V, t
- **PR #15764** (build_system): > Hmmm though now it does seem like the qemu tests are failing for some reason  It looks like GitHub Actions have updated ubuntu-latest to ubuntu-24

**Closing References:** 0

---

## Issue #13 (cloned from #18820)

**Title:** [TRIAGE TEST #18820] ports/zephyr fails to compile with CONFIG_BT=y : 'CONFIG_BT_DEVICE_NAME_MAX' undeclared

**Original Labels:** (none)

**Prompt length:** 15,621 chars

### Similar Issues (9 total)

| # | Title | State | RRF Score |
|---|-------|-------|-----------|
| 18312 | NUCLEO_G0B1RE fails to build if CAN is enabled | open | 0.0228 |
| 15154 | Build a esp32 firmware with version 1.22.2 meet a build issuse | open | 0.0226 |
| 18351 | C++ STL modules fail to link on some bare metal platforms | open | 0.0180 |
| 17353 | Build fails for port/unix mips/mipsel | open | 0.0164 |
| 13428 | heap-buffer-overflow [micropython@a5bdd39127]  | open | 0.0161 |

### Duplicate Candidates

| # | Title | State | RRF Score |
|---|-------|-------|-----------|
| 4839 | esp32 PPP compile errors | closed | 0.0302 |
| 7329 | build micropython for qemu failed .ports:zephyr | closed | 0.0279 |
| 4111 | micropython unix fail to build... | closed | 0.0262 |

### Related Reviews (5 total)

- **PR #7641** (api_design): As above, I think this attribute should be a method to match other classes.
- **PR #9335** (build_system): I've rebased this on latest master, and squashed some of the commits, and force-pushed to this branch.  I was ready to merge it but the CI is not ha
- **PR #6543** (documentation): that's technically not exactly true, and is a little bit misleading... every grammar node defined by `DEF_RULE` has a corresponding compile function i

**Closing References:** 0

---

## Issue #14 (cloned from #18839)

**Title:** [TRIAGE TEST #18839] SEEED_XIAO_RP2350: Flash size configured as 4MB, board only has 2MB

**Original Labels:** (none)

**Prompt length:** 10,632 chars

### Similar Issues (9 total)

| # | Title | State | RRF Score |
|---|-------|-------|-----------|
| 17867 | SEEED_XIAO_NRF52 board access to 1 MB Flash | open | 0.0317 |
| 16391 | Seeed Studio XIAO RP2350 doesn't boot | open | 0.0285 |
| 8680 | rp2: per-board custom memmap_mp.ld to enforce configured flash size | open | 0.0284 |
| 18076 | RP2: ADC pins does not work properly in XIAO RP2350 | open | 0.0255 |
| 6553 | ESP32 execute esp.read_flash() cause exception  | open | 0.0254 |

### Duplicate Candidates

| # | Title | State | RRF Score |
|---|-------|-------|-----------|
| 17867 | SEEED_XIAO_NRF52 board access to 1 MB Flash | open | 0.0315 |
| 17375 | RP2350: Flash clock frequency problem | closed | 0.0304 |
| 8753 | docs: alternative build options required for `port/rp2` | closed | 0.0295 |

### Related Reviews (5 total)

- **PR #17389** (correctness): Unfortunately this broke SIL_RP2040_SHIM: ``` $ make BOARD=SIL_RP2040_SHIM ... [ 48%] Building C object CMakeFiles/firmware.dir/rp2_flash.c.o mic
- **PR #17452** (memory): Thanks for updating, this looks good now.  I've squashed the commits to one per port, and made a few minor fixes: - increased ROM partition size fr
- **PR #16313** (memory): Might want to decrease the filesystem size by a bit more to make room for a future ROMFS (see #8381).  It has 4MiB flash (right?) so maybe reserve 1.5

**Closing References:** 0

---

## Issue #15 (cloned from #18875)

**Title:** [TRIAGE TEST #18875] docs: No instructions for REPL over UART on RP2

**Original Labels:** (none)

**Prompt length:** 8,470 chars

### Similar Issues (9 total)

| # | Title | State | RRF Score |
|---|-------|-------|-----------|
| 8560 | How can I access non-REPL UART over USB? | open | 0.0320 |
| 17672 | ESP32-C6, ESP32-S3, etc.: MICROPY_HW_ENABLE_UART_REPL should be disabled for boa | open | 0.0308 |
| 5405 | Move esp32 REPL to a different UART | open | 0.0301 |
| 8333 | Documentation Improvement Suggestion: esp8266/quickref.rst WebREPL UART + RXBUF | open | 0.0290 |
| 16611 | [feature request] being able to change UART(0) speed without recompiling. | open | 0.0265 |

### Duplicate Candidates

| # | Title | State | RRF Score |
|---|-------|-------|-----------|
| 11057 | REPL over UART not working on the RP2 port | closed | 0.0387 |
| 8560 | How can I access non-REPL UART over USB? | open | 0.0317 |
| 1499 | REPL don't start via UART on CC3200 version | closed | 0.0299 |

### Related Reviews (5 total)

- **PR #6925** (testing): @UnexpectedMaker I tested this on a FeatherS2 and it works!  As mentioned above no USB yet but it does give a REPL over UART.
- **PR #3184** (testing): Did you test that the REPL works on this UART?
- **PR #3137** (testing): I tried this PR out on 2 devices: - PCA10036 (engineering A version of nRF52832): I can get a UART REPL but enable the soft device S132 doesn't work,

**Closing References:** 0

---

## Issue #16 (cloned from #18851)

**Title:** [TRIAGE TEST #18851] Still no IPv4 Hostname advertisement with stock LwIP and stock mDNS IPv6 does however.

**Original Labels:** (none)

**Prompt length:** 9,082 chars

### Similar Issues (9 total)

| # | Title | State | RRF Score |
|---|-------|-------|-----------|
| 18024 | rp2/W5100S-EVB-PICO does not seem to send a hostname to DHCP server when getting | open | 0.0323 |
| 17976 | Setting hostname on Pico W (still) has no effect: no host name is exposed (also  | open | 0.0310 |
| 17127 | Unable to setup IP with nic.ipconfig() while works with obsolete nic.ifconfig()  | open | 0.0299 |
| 15127 | wiznet: spi baudrate declared as 2 and 20 MHz ?! | open | 0.0288 |
| 17242 | wiznet5k_send_ethernet: fatal error -5 | open | 0.0274 |

### Duplicate Candidates

| # | Title | State | RRF Score |
|---|-------|-------|-----------|
| 18024 | rp2/W5100S-EVB-PICO does not seem to send a hostname to DHCP server when getting | open | 0.0323 |
| 17976 | Setting hostname on Pico W (still) has no effect: no host name is exposed (also  | open | 0.0310 |
| 17975 | Setting hostname on Pico W (still) has no effect: no host name is exposed (also  | closed | 0.0310 |

### Related Reviews (5 total)

- **PR #8918** (api_design): > The idea was to support `config('hostname')` followed by `active(True)`  On esp32 you need to run `active(True)` before `config(hostname=...)`, or
- **PR #18303** (build_system): As above, IMO should use the standard hostname.
- **PR #12404** (correctness): This is a problem... the network interface (eg WLAN) usually stays up over a soft reset, but now the hostname is being reset.  In particular a call

**Closing References:** 0

---
