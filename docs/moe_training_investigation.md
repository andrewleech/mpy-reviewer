# MoE Fused Kernel Probe & Training Decision

Investigation into accelerating Qwen3-Next 80B MoE fine-tuning on piai (RTX 8000, sm_75, 46GB VRAM).

## Hardware Constraints

- RTX 8000 Turing (sm_75): no bf16, no FA2, no TF32
- VRAM: 44.8 / 46GB used (97.3%), ~5GB free during training
- Root filesystem was 100% full (1.8TB) after a 98GB failed HF download; resolved by pointing `HF_HOME` to `/srv/data/.cache/huggingface`

## Probe Results

| Test | Result | Notes |
|------|--------|-------|
| Triton 3.6 sm_75 compilation | PASS | Contrary to Triton docs declaring sm_75 unsupported |
| Fused grouped GEMM | FAIL | 4-bit weights incompatible |
| Baseline MoE block forward | 108ms | 512 experts, top_k=10, sequential dispatch |

The fused kernel path (`unsloth/kernels/moe/grouped_gemm/`) requires `extract_hf_weights()` to stack expert weights into `[E, N, K]` fp16 tensors. With 4-bit NF4 quantization, weights are `Linear4bit` -> `Params4bit` -> packed `uint8` which can't be used for matmul. Dequantizing would need ~9GB VRAM (exceeds the 5GB free).

Other dead ends:
- Unsloth + DeepSpeed: breaks custom kernels, VRAM 6.4GB -> 33GB (issues #225, #919, #2723)
- DeepSpeed + bitsandbytes 4-bit: `ValueError: .to is not supported for 4-bit or 8-bit models`

## Training Decision

Reduced from 3 epochs to 1 epoch to get a usable checkpoint faster:

| | 3 epochs | 1 epoch |
|---|----------|---------|
| Steps | 1,569 | 523 |
| Speed | 754 s/step | ~550 s/step |
| ETA | 13.6 days | ~3.3 days |

## Environment

```bash
HF_HOME=/srv/data/.cache/huggingface
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
CUDA_VISIBLE_DEVICES=0
```

Training runs in a tmux session on piai:
```bash
cd /srv/data/micropython-expert && source venv/bin/activate
HF_HOME=/srv/data/.cache/huggingface \
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
CUDA_VISIBLE_DEVICES=0 \
python training/train_sft.py
```

## Monitoring

```bash
# Training progress
ssh piai "tmux capture-pane -t training -p | tail -3"

# GPU utilization
ssh piai "nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw --format=csv,noheader"

# HF cache symlink
ssh piai "ls -la /home/anl/.cache/huggingface"
```

## Next Steps

1. Wait for 1-epoch training to complete (~3.3 days from step 17/523)
2. Evaluate: `python training/evaluate.py --model ./models/micropython-expert-qwen3-next --unsloth`
   - Target: >2.5/5 (v1 baseline was 1.79-2.02)
3. If quality sufficient, proceed to DPO
4. If not, consider cloud GPU (A100/H100 with full fused kernel support) or a dense model (Qwen2.5-Coder-32B)

## Versions

- PyTorch 2.10.0+cu128
- Triton 3.6.0
- Unsloth 2026.2.1
