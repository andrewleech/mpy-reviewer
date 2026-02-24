# Eval Results: Fine-Tuned Model vs Claude + RAG for MicroPython Code Review

**Date:** 2026-02-09
**Evaluator:** Opus 4.6 (LLM-as-judge)

## Experiment Design

**Objective:** Determine whether fine-tuned or larger open-weight models can match Claude (Sonnet 4.5 / Opus 4.6) with or without RAG for dpgeorge-style MicroPython code review.

**Variants tested:**

| ID | Model | Backend | RAG | Notes |
|----|-------|---------|-----|-------|
| ft_f16 | micropython-expert:f16 | Ollama | No | Fine-tuned Qwen2.5-Coder-7B, F16 precision |
| ft_q4 | micropython-expert:q4-k-m | Ollama | No | Same model, Q4_K_M quantization |
| ft_f16_rag | micropython-expert:f16 | Ollama | Yes | F16 with RAG prompt (review examples + codebase context) |
| base_qwen | qwen2.5-coder:7b-instruct | Ollama | No | Base (non-fine-tuned) Qwen2.5-Coder-7B, Q4 |
| base_qwen_rag | qwen2.5-coder:7b-instruct | Ollama | Yes | Base model with RAG prompt |
| qwen3_coder | qwen3-coder-next:q4_K_M | Ollama | No | Qwen3-Coder-Next 80B-A3B MoE (Q4_K_M, no RAG) |
| qwen3_coder_rag | qwen3-coder-next:q4_K_M | Ollama | Yes | Qwen3-Coder-Next 80B-A3B MoE (Q4_K_M, with RAG) |
| sonnet_bare | claude-sonnet-4-5-20250929 | Claude CLI | No | Sonnet 4.5, bare prompt |
| sonnet_rag | claude-sonnet-4-5-20250929 | Claude CLI | Yes | Sonnet 4.5 with RAG prompt |
| opus_bare | claude-opus-4-6 | Claude CLI | No | Opus 4.6, bare prompt |
| opus_rag | claude-opus-4-6 | Claude CLI | Yes | Opus 4.6 with RAG prompt |

**Test PRs (5 selected for domain diversity):**

| PR | Title | Domain |
|----|-------|--------|
| #17418 | pyproject.toml: Enforce trailing newline on python files | build_system, code_style |
| #18347 | tests/extmod: Make test time_res.py more deterministic | testing |
| #18451 | mimxrt: Fix SD card deadlock and timeout handling | correctness, error_handling |
| #18785 | mpremote: Speed up file transfers with automatic encoding | performance, tools |
| #18416 | py: Add enum support and minimal metaclass features | api_design, architecture |

**Protocol:** 3 repeats per (variant, PR) = 165 planned reviews (7 original + 2 base Qwen 7B + 2 Qwen3-Coder-Next 80B). Temperature 0.7 for all models. Expanded diffs (`git diff -U200`) for full context. Static prompts only (no tool use). All tools disabled via `--tools ""` for Claude variants.

**Scoring:** Opus 4.6 as judge, 6 criteria (1-5 scale) with anchored rubrics: technical accuracy, relevance, completeness, actionability, style fidelity, severity calibration. JSON schema enforcement for structured output. Consistency analysis across 3 repeats per group.

## Results Summary

**141 of 165 reviews scored** (24 unscorable due to Ollama timeouts on large prompts).

### Overall Rankings

| Rank | Variant | Mean (1-5) | Consistency (1-5) | n |
|------|---------|-----------|-------------------|---|
| 1 | opus_rag | 3.59 | 4.40 | 15 |
| 2 | opus_bare | 3.37 | 4.00 | 15 |
| 3 | sonnet_rag | 2.90 | 3.60 | 15 |
| 4 | sonnet_bare | 2.63 | 4.20 | 15 |
| 5 | qwen3_coder | 2.56 | 3.00 | 11 |
| 6 | qwen3_coder_rag | 2.24 | 2.75 | 14 |
| 7 | ft_f16_rag | 2.02 | 1.67 | 9 |
| 8 | ft_f16 | 1.87 | 1.00 | 14 |
| 9 | ft_q4 | 1.79 | 1.75 | 14 |
| 10 | base_qwen | 1.42 | 2.33 | 11 |
| 11 | base_qwen_rag | 1.08 | 1.50 | 8 |

### Per-Criterion Breakdown (top and bottom)

| Criterion | Best (opus_rag) | Worst (base_qwen_rag) | Gap |
|-----------|----------------|----------------------|-----|
| Technical Accuracy | 3.80 | 1.13 | 2.67 |
| Relevance | 4.27 | 1.00 | 3.27 |
| Completeness | 3.87 | 1.00 | 2.87 |
| Actionability | 3.87 | 1.00 | 2.87 |
| Style Fidelity | 2.40 | 1.13 | 1.27 |
| Severity Calibration | 3.33 | 1.25 | 2.08 |

## Key Findings

### 1. Qwen3-Coder-Next 80B MoE nearly matches Sonnet 4.5

The Qwen3-Coder-Next 80B-A3B MoE (Q4_K_M quantized, ~52GB) scores 2.56 bare — within 0.07 of Sonnet 4.5 bare (2.63). It particularly excels at completeness (3.27) and actionability (3.36), approaching Sonnet-level performance on those criteria. Technical accuracy (2.64) and severity calibration (2.36) are reasonable. Consistency (3.00/5) is moderate — better than all 7B models but below Claude variants.

The 80B MoE model produces structured, detailed code reviews that identify real issues from the diff, reference specific code constructs, and provide actionable suggestions. It handles prompts up to ~35K chars within the 600s timeout but times out on the 113K bare prompt for PR #18416 (same context overflow pattern as the 7B models, since all run with `num_ctx: 32768`).

### 2. RAG hurts the 80B MoE model

RAG reduces qwen3_coder's score from 2.56 to 2.24 (delta -0.32). This is the same pattern seen with the base 7B model but unexpected for an 80B model. The degradation is concentrated in technical accuracy (2.64 → 1.86) and severity calibration (2.36 → 1.79), while actionability is unaffected (3.36 → 3.43).

Unlike the 7B model where RAG caused obvious hallucination from context overflow, the 80B model handles the RAG prompt lengths fine (14/15 RAG runs succeeded vs 11/15 bare). The quality degradation may stem from the RAG context's dpgeorge-style examples biasing the model toward brevity without substance, or the additional instruction complexity degrading focus on the actual diff.

### 3. Fine-tuned 7B model underperforms significantly

The fine-tuned Qwen2.5-Coder-7B scores 1.79-2.02 mean vs 2.63-3.59 for Claude. The gap is largest on completeness (1.21 vs 3.87) and relevance (1.93 vs 4.27). The judge characterized multiple fine-tuned outputs as "fabricated responses that don't engage with the actual diff" and "not code reviews at all — PR descriptions written from the author's perspective."

The fine-tuned model appears to have learned the *format* of GitHub comments (merge acknowledgments, PR descriptions, contributor updates) rather than the *substance* of code review.

### 2. Fine-tuned model has near-zero consistency

Consistency scores: ft_f16 = 1.0/5, ft_q4 = 1.75/5, ft_f16_rag = 1.67/5. All Claude variants score 3.6-4.4/5. The fine-tuned model produces fundamentally different outputs on each run — different issues, different perspectives, different formats. This makes it unreliable for any practical review workflow.

### 5. RAG helps Claude models, hurts open-weight models

| Model | Bare | RAG | Delta |
|-------|------|-----|-------|
| Opus 4.6 | 3.37 | 3.59 | +0.22 |
| Sonnet 4.5 | 2.63 | 2.90 | +0.27 |
| Qwen3-Coder-Next 80B | 2.56 | 2.24 | **-0.32** |
| Fine-tuned F16 | 1.87 | 2.02 | +0.15 |
| Base Qwen 7B | 1.42 | 1.08 | **-0.34** |

RAG improves Claude variants and the fine-tuned 7B, but hurts both non-fine-tuned open-weight models. For Claude, RAG's largest impact is on style fidelity and relevance. For the 80B MoE and base 7B, the additional context degrades technical accuracy and calibration — the RAG examples may bias the model toward a review style it can't execute well, replacing its native review approach with a worse imitation.

### 6. Quantization impact is negligible

F16 vs Q4_K_M delta is -0.08 overall (1.87 vs 1.79). The fine-tuned model's poor performance is not a quantization artifact — it's a fundamental capability gap.

### 7. Fine-tuning improved the base 7B model

Comparing base Qwen2.5-Coder-7B-Instruct against the fine-tuned version on the same prompts:

| Variant | Bare | RAG |
|---------|------|-----|
| Base Qwen 7B | 1.42 | 1.08 |
| Fine-tuned Qwen 7B (F16) | 1.87 | 2.02 |
| Fine-tuning delta | +0.45 | +0.94 |

Fine-tuning helped on every criterion. The improvement is largest on technical accuracy (+0.36 bare) and relevance (+0.50 bare). The base model's primary failure is producing generic, padded reviews that don't engage with the specific diff — it addresses "memory efficiency", "API design", and "portability" even on trivial one-line config changes. The fine-tuned model at least sometimes identifies actual code issues from the diff.

RAG *hurts* the base model (1.42 → 1.08, a -0.34 delta) — the additional context confuses the 7B model into fabricating issues and referencing non-existent code constructs. The fine-tuned model shows the opposite pattern: RAG helps (1.87 → 2.02, +0.15). This suggests fine-tuning taught the model to extract signal from longer prompts.

The fine-tuned model still underperforms all Claude variants, and its outputs suffer from role confusion (generating PR author comments instead of reviews). But without fine-tuning, the base 7B model is worse on every measure.

### 8. Style fidelity is universally weak

Even the best variant (opus_rag at 2.40/5) struggles to match dpgeorge's terse, inline comment style. All Claude variants produce verbose, structured reviews with headers and numbered lists. The fine-tuned model scores slightly higher on style (2.21-3.00) because it sometimes produces short, terse outputs — but only because those outputs lack substantive content, not because they match dpgeorge's precision.

### 9. Opus >> Sonnet for review quality

Opus outperforms Sonnet across every criterion except actionability (where they're close). The gap is largest on technical accuracy (3.53 vs 2.53 bare, 3.80 vs 2.67 RAG) and severity calibration (3.20 vs 2.20 bare).

## Failure Modes

### Base (non-fine-tuned) Qwen 7B

- **Generic reviews:** Addresses every review criterion (memory, API, portability, performance) even on trivial changes, producing template-like output disconnected from the actual diff
- **RAG confusion:** RAG context causes hallucination — references variables, functions, and security concerns not present in the diff. RAG reduced score from 1.42 to 1.08
- **No domain knowledge:** Doesn't understand MicroPython conventions, embedded constraints, or project architecture
- **Context handling:** Same timeout patterns as fine-tuned model on large prompts

### Fine-tuned model

- **Role confusion:** Generates PR author comments, merge acknowledgments, and contributor updates instead of reviews
- **Hallucination:** References code constructs and issues not present in the diff
- **Inconsistency:** 3 runs on the same PR produce completely unrelated outputs
- **Context handling:** Consistently times out or crashes on prompts >68K chars (RAG) and sometimes on >112K chars (bare)

### Qwen3-Coder-Next 80B MoE

- **Style mismatch:** Produces structured, verbose reviews with headers, numbered lists, and severity labels — scores 1.00/5 on style fidelity, the worst of any variant (the 7B models occasionally produce short output that accidentally scores higher on style)
- **RAG degradation:** RAG context reduces technical accuracy from 2.64 to 1.86 — the model attempts to mimic dpgeorge's style from examples but loses accuracy in the process
- **Context limits:** Times out on prompts exceeding ~32K tokens (113K chars bare prompt for PR #18416), same limitation as 7B models since all use `num_ctx: 32768`
- **Inconsistency on small PRs:** Consistency is only 2/5 on PR #17418 (trivial config change), suggesting the model over-generates on simple changes

### Claude variants

- **Verbosity:** All Claude variants are significantly more verbose than dpgeorge's actual style
- **Structure:** Uses markdown headers, numbered lists, severity labels — dpgeorge uses terse inline comments
- **Diff truncation sensitivity:** Some accuracy issues stem from reviewing truncated diffs where definitions are missing

## Operational Notes

### Execution

- Phase 2 (review generation): Claude variants ran in parallel (3 workers), Ollama sequential. Original 7 variants ~2.5 hours. Base Qwen variants: bare ~74 min, RAG ~87 min. Qwen3-Coder-Next variants: bare ~65 min, RAG ~49 min.
- Phase 3 (judging): 141 individual + 43 consistency = 184 Opus judge calls total.
- Estimated API cost: ~$22-26 for judging + ~$8-12 for Claude review variants.

### Issues encountered during execution

1. **`claude -p` inherits project skills/CLAUDE.md** — Opus attempted to invoke installed skills instead of producing text output. Fixed by using `--tools ""` and `--append-system-prompt` to override.
2. **`claude -p --output-format json` response format** — The `result` field was empty string or raw JSON envelope for budget-exceeded calls. Fixed by properly parsing `claude_output.get("result") or ""` and checking `subtype`.
3. **`claude -p --json-schema` output location** — Structured output goes to `output["structured_output"]`, not `output["result"]`. Discovered and fixed during judge implementation.
4. **Ollama timeouts** — F16 model times out at 600s on prompts >45K chars over SSH tunnel. 8 of 105 reviews failed this way (all fine-tuned RAG variants on the two largest PRs).
5. **Ollama Docker upgrade** — Qwen3-Coder-Next required Ollama v0.15.5+ (existing was v0.13.0). Upgraded Docker container from v0.13.0 to v0.15.6. Models persisted in named volume `ollama:/root/.ollama`.
6. **Qwen3-Coder-Next model size** — Q4_K_M variant is 51.7GB, 79.7B params. Required deleting older models to free disk space on the 46GB VRAM RTX 8000 host.

## Data Location

All raw data is in `eval/benchmark/`:
- `prompts/bare/` and `prompts/rag/` — input prompts per PR
- `diffs/` — expanded diffs per PR
- `results/<variant>/` — review outputs (JSON with response, timing, metadata)
- `scores/<variant>/` — judge scores and consistency analysis
- `report/summary.md` — auto-generated analysis report

## Next Steps

- [x] ~~Test base (non-fine-tuned) Qwen2.5-Coder-7B-Instruct to determine if fine-tuning helped or hurt~~ — Completed: fine-tuning helped (+0.45 bare, +0.94 RAG)
- [x] ~~Test larger base model to determine if 7B parameter count is the primary bottleneck~~ — Completed: Qwen3-Coder-Next 80B MoE (2.56) nearly matches Sonnet 4.5 (2.63), confirming model scale was the main limitation
- [ ] Investigate why RAG hurts open-weight models — the 80B MoE loses 0.32 mean with RAG despite handling the context length fine. The RAG prompt structure may need adaptation for non-Claude models
- [ ] Fine-tune Qwen3-Coder-Next on (diff → review) pairs — the 80B base already scores 2.56; fine-tuning on clean reviewer-only data could potentially match or exceed Sonnet
- [ ] Test with increased `num_ctx` (64K or 128K) for the 80B model to handle PR #18416 — the model supports 256K natively
- [ ] Investigate prompt engineering for style fidelity improvement — all models score poorly (1.0-2.4/5), with the 80B MoE scoring worst despite producing the most substantive reviews
- [ ] Consider whether the fine-tuning data (review comments, not code review instructions) produced the wrong behavior — the role confusion issue suggests training on PR comments (which include author messages, not just reviewer comments) may have confused the 7B model about its role
