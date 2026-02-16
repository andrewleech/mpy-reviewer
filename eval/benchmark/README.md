# Benchmark: Fine-Tuned Model vs Claude + RAG for Code Review

Compares review quality across 7 model/RAG configurations on 5 real MicroPython PRs.

## Test Matrix

7 variants x 5 PRs x 3 repeats = **105 reviews**

| # | Variant ID | Model | RAG | Backend |
|---|------------|-------|-----|---------|
| 1 | `ft_f16` | micropython-expert:f16 | No | Ollama (piai) |
| 2 | `ft_q4` | micropython-expert:q4-k-m | No | Ollama (piai) |
| 3 | `ft_f16_rag` | micropython-expert:f16 | Yes | Ollama (piai) |
| 4 | `sonnet_bare` | Claude Sonnet 4.5 | No | claude -p |
| 5 | `opus_bare` | Claude Opus 4.6 | No | claude -p |
| 6 | `sonnet_rag` | Claude Sonnet 4.5 | Yes | claude -p |
| 7 | `opus_rag` | Claude Opus 4.6 | Yes | claude -p |

## Test PRs

| PR | Title | Domain |
|----|-------|--------|
| #17418 | pyproject.toml: Enforce trailing newline on python files | build_system, code_style |
| #18347 | tests/extmod: Make test time_res.py more deterministic | testing |
| #18451 | mimxrt: Fix SD card deadlock and timeout handling | correctness, error_handling |
| #18785 | mpremote: Speed up file transfers with automatic encoding | performance, tools |
| #18416 | py: Add enum support and minimal metaclass features | api_design, architecture |

PR #18416 is 71 files / 15K lines — only the 10 most substantive files are included in its diff.

## Information Fairness

All models receive pre-generated static prompts (no interactive tool use). This isolates review capability from tool-use capability.

**Expanded diffs**: `git diff -U200` provides ~200 lines of context around each hunk (standard `gh pr diff` only gives 3), so models can see the full surrounding function/struct.

**"Bare" variants** receive: expanded diff + PR metadata + task instructions (review criteria, severity levels).

**"RAG" variants** receive: maintainer style guide (~900 tok) + 8 retrieved review examples (~4000 tok) + codebase context from codanna (~1000 tok) + expanded diff + task instructions.

**Claude tool access**: Disabled via `--disallowed-tools` to prevent independent codebase exploration.

**Fine-tuned context window**: Ollama overridden to `num_ctx: 32768` (default Modelfile is 4096).

## Evaluation

### LLM-as-Judge (Opus)

Each of the 105 reviews scored on 6 criteria (1-5 scale):

1. **Technical accuracy** — Are identified issues real?
2. **Relevance** — Does the review focus on important aspects?
3. **Completeness** — Did it catch major issues?
4. **Actionability** — Are suggestions specific enough to act on?
5. **Style fidelity** — Does it match the lead maintainer's direct, terse style?
6. **Severity calibration** — Are blocking/suggestion/nitpick levels appropriate?

### Consistency Analysis

For each (variant, PR) group of 3 repeats, the judge also assesses cross-repeat consistency and identifies the best and worst repeat.

### Manual Review

`analyze.py` generates a manual review index pointing to the best/worst repeats for side-by-side inspection.

## Running the Benchmark

### Prerequisites

- SSH tunnel to piai: `ssh -L 11435:localhost:11434 piai`
- `micropython-expert:f16` and `micropython-expert:q4-k-m` loaded in Ollama on piai
- `claude` CLI available locally
- `mpy-reviewer` installed (`pip install -e .` from project root)
- `gh` CLI authenticated with access to micropython/micropython

### Execution

```bash
cd eval/benchmark

# Phase 1: Fetch diffs, generate prompts (~2 min)
python prepare.py

# Phase 2a: Run fine-tuned variants (~30 min, sequential)
python run.py --variants ft_f16,ft_q4,ft_f16_rag

# Phase 2b: Run Claude variants (~20 min, parallel)
python run.py --variants sonnet_bare,opus_bare,sonnet_rag,opus_rag

# Phase 3: Judge all 105 reviews (~30 min)
python judge.py

# Phase 4: Generate report (instant)
python analyze.py
```

All phases are resume-capable — they skip already-completed work on re-run.

### Quick Smoke Test

```bash
# Test with a single PR, single repeat
python prepare.py --pr 18347
python run.py --variants sonnet_bare --prs 18347 --repeats 1
python judge.py --variants sonnet_bare --prs 18347
python analyze.py
```

### Estimated Cost

| Component | Cost |
|-----------|------|
| Sonnet reviews (30 calls) | ~$0.75 |
| Opus reviews (30 calls) | ~$4.05 |
| Judge pass 1 (105 calls) | ~$7.35 |
| Judge pass 2 (35 calls) | ~$3.50 |
| **Total** | **~$16-18** |

## Directory Structure

```
eval/benchmark/
├── variants.py         # Variant definitions, PR list, prompt construction
├── prepare.py          # Phase 1: fetch diffs, generate bare/RAG prompts
├── run.py              # Phase 2: execute all variants via Ollama/claude
├── judge.py            # Phase 3: LLM-as-judge scoring (individual + consistency)
├── analyze.py          # Phase 4: aggregate scores, generate report
├── diffs/              # Cached expanded-context diffs (generated)
├── prompts/            # Pre-generated prompts (generated)
│   ├── bare/           #   diff + task instructions
│   └── rag/            #   style guide + examples + codebase + diff + task
├── results/            # Raw review outputs (generated)
│   └── {variant_id}/
├── scores/             # Judge scores (generated)
│   └── {variant_id}/
└── report/
    └── summary.md      # Final analysis (generated)
```

## Bias Note

Opus is both a test variant and the judge. Scores for `opus_bare` and `opus_rag` may be inflated. This is accepted since Opus is the strongest available model for judging.
