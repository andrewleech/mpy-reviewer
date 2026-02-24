# Cloud GPU Inference Options

Options for running inference with the fine-tuned Qwen3-Coder-Next 80B MoE model
when piai (RTX 8000) is unavailable.

The review workflow has two parts:
1. **Local RAG retrieval** — CPU only, runs `mpy-review-rag review --pr <N> --output prompt`
2. **LLM inference** — needs GPU or API, consumes the prompt from step 1

Only the inference step needs cloud resources.

## Model Requirements

- Qwen3-Coder-Next 80B MoE, LoRA-merged
- GGUF format at Q4_K_M: ~45-50 GB (fits single A100 80GB)
- GGUF format at Q8_0: ~80 GB (needs H100 80GB or larger)
- Inference via llama.cpp / vLLM / similar

## Platform Comparison

| Platform | Type | Fine-Tuned Model | Serverless | Cold Start | GPU Hourly Rate | Scripted Lifecycle |
|---|---|---|---|---|---|---|
| **Together.ai** | Managed API | Yes (dedicated endpoints) | Yes | <100ms | H100: $3.36/hr | N/A (always-on endpoint) |
| **Fireworks.ai** | Managed API | Yes (upload custom weights) | Yes | ~1 min from zero | H100: $4.00/hr | N/A (always-on endpoint) |
| **RunPod** | Serverless GPU | Yes (GGUF via custom worker) | Yes | 0.5-30s (FlashBoot) | A100: $2.74/hr, H100: $4.18/hr | Python SDK |
| **Modal** | Serverless GPU | Yes (any model) | Yes | 2-12s (GPU snapshots) | A100 80GB: $2.50/hr, H100: $3.95/hr | Python SDK |
| **Vast.ai** | GPU Marketplace | Yes (GGUF via llama.cpp) | No | 30s-5 min | A100: $0.43-1.00/hr, H100: $1.87-4.00/hr | `vastai` CLI |
| **Lambda Labs** | On-Demand VMs | No (catalog models only) | No | N/A | A100: $1.79/hr, H100: $2.49-3.29/hr | No |
| **Jarvis Labs** | On-Demand VMs | No (manual setup) | No | <90s | H100: $2.99/hr | JLClient Python SDK |

Pricing as of February 2026. Vast.ai rates are marketplace-driven and fluctuate.

## Fine-Tuned Model Deployment Constraints

**Managed APIs (Together.ai, Fireworks.ai)** now support uploading custom fine-tuned
weights to dedicated endpoints. However, both have architecture constraints — an 80B MoE
in GGUF format may not be among supported architectures since these platforms optimize for
their own serving stack (not llama.cpp). Verify Qwen3-Coder-Next compatibility before
committing to this path. Dedicated endpoints also have minimum billing commitments
(typically hourly) which makes them expensive for sporadic use.

**Serverless platforms (RunPod, Modal)** accept arbitrary container images, so any model
loadable by llama.cpp or vLLM works. This is the most flexible option for custom GGUF
models.

**Marketplace (Vast.ai)** provides raw GPU instances where you control the full stack.
Pre-built llama.cpp templates with GGUF support are available. Cheapest per-hour cost but
no managed serving layer.

**VM rental (Lambda Labs, Jarvis Labs)** is pure infrastructure — you SSH in, install
dependencies, run inference manually. No serverless, no API-based deployment. Lambda's
inference API only serves their catalog models.

## Scriptable On-Demand Workflow

```
mpy-expert-review PR 123
  |
  +-- Local: mpy-review-rag review --pr 123 --output prompt
  |     (RAG retrieval, CPU only, ~2-4 seconds)
  |
  +-- Cloud: spin up GPU instance / invoke serverless endpoint
  |     (platform-dependent, see cold start times above)
  |
  +-- Cloud: load fine-tuned GGUF model into GPU memory
  |     (10-30s from SSD, longer from network storage)
  |
  +-- Cloud: send prompt, receive review text
  |     (inference time for ~8k context + generation)
  |
  +-- Cloud: destroy instance / let serverless scale down
```

Model loading dominates cold start time. Platforms with model caching mitigate this:
- **RunPod**: Network volumes keep the GGUF on fast SSD attached to workers
- **Modal**: GPU memory snapshots checkpoint the fully-loaded model state, restore in ~2-5s
- **Vast.ai**: No caching — model must be downloaded or pre-staged on instance storage

### RunPod Implementation Sketch

```python
from runpod import Endpoint

endpoint = Endpoint(api_key=RUNPOD_KEY, endpoint_id=ENDPOINT_ID)
result = endpoint.run_sync({"prompt": rag_prompt, "max_tokens": 4096})
```

The custom worker handler loads the GGUF from a network volume and serves via llama.cpp.
FlashBoot retains worker state after idle timeout, enabling sub-second restarts for
returning traffic.

### Modal Implementation Sketch

```python
import modal

app = modal.App("mpy-review")
volume = modal.Volume.from_name("model-weights")

@app.cls(gpu="H100", volumes={"/models": volume})
class Reviewer:
    def __enter__(self):
        # Load GGUF model once per container lifecycle
        self.llm = load_gguf("/models/qwen3-coder-next-80b-q4_k_m.gguf")

    @app.method()
    def review(self, prompt: str) -> str:
        return self.llm.generate(prompt, max_tokens=4096)
```

With GPU memory snapshots enabled, the loaded model state is checkpointed and restored
in ~2-5 seconds on subsequent invocations.

### Vast.ai Implementation Sketch

```bash
# Find cheapest A100 with enough disk
OFFER=$(vastai search offers --gpu-name A100 --disk 100 --order dph --raw | jq '.[0].id')

# Create instance with llama.cpp template
INSTANCE=$(vastai create instance $OFFER --image vastai/llama-cpp --disk 100)

# Wait for ready, then run inference via SSH
vastai ssh $INSTANCE "llama-server -m /models/model.gguf --port 8080 &"
curl http://$INSTANCE_IP:8080/completion -d '{"prompt": "...", "n_predict": 4096}'

# Destroy when done
vastai destroy instance $INSTANCE
```

Full lifecycle is scriptable via the `vastai` CLI. No warm hosting — each invocation
pays the full cold start cost (instance creation + model download).

## Warm Hosting and Scale-to-Zero

| Platform | Scale to Zero | Warm Hosting | Idle Cost | Resume Time |
|---|---|---|---|---|
| **RunPod** | Yes (flex workers) | Yes (active workers) | $0 idle (flex), ~$2-4/hr (active) | 0.5-30s (FlashBoot) |
| **Modal** | Yes (default) | Yes (`min_containers=1`) | $0 idle (default), ~$4/hr (min 1) | 2-5s (GPU snapshots) |
| **Vast.ai** | Manual destroy | No (stop/start preserves disk) | Stopped instance still billed for storage | 30s-5 min |
| **Together.ai** | Serverless: yes | Dedicated: always-on | Dedicated endpoint billed continuously | <100ms (serverless) |
| **Fireworks.ai** | Serverless: yes | Dedicated: always-on | Dedicated endpoint billed continuously | ~1 min (serverless from zero) |

**RunPod** offers the most granular warm hosting: set 1 active worker to keep the model
pre-loaded at ~$2-4/hr, with additional flex workers scaling to zero. FlashBoot further
reduces cold starts for flex workers.

**Modal** GPU memory snapshots are the fastest cold-start option. The GPU state (model
weights in VRAM, compiled CUDA kernels) is checkpointed to disk and restored in ~2-5
seconds. This avoids the 10-30 second model loading step entirely.

**Vast.ai** has no native warm hosting. Stopped instances retain disk state but still
incur storage charges. The cheapest raw GPU cost but highest operational overhead.

## Recommendations

**Occasional use (a few reviews per week):**
Vast.ai on-demand via `vastai` CLI. A100 instances at ~$0.50-1.00/hr, full scripted
lifecycle. Pay only for the ~2-5 minutes of actual inference per review. Cold start
overhead (instance creation + model load) adds 3-5 minutes per session, acceptable at
low frequency.

**Regular use (multiple reviews per day):**
RunPod serverless with 0 active workers and FlashBoot. Model stored on network volume.
Flex workers scale to zero when idle ($0 cost). Cold start of 10-30s on first request,
sub-second on subsequent requests within the idle timeout window. Cost: ~$2.74/hr (A100)
or ~$4.18/hr (H100) only during active inference.

**Lowest latency (sub-5-second end-to-end):**
Modal with GPU memory snapshots. Model state checkpointed in GPU memory, restored in
~2-5 seconds. Per-second billing means you pay only for inference time. Best developer
experience (Python SDK, infrastructure-as-code). Cost: ~$2.50/hr (A100 80GB) or
~$3.95/hr (H100) during active inference.

**Highest throughput (batch reviewing many PRs):**
RunPod serverless with autoscaling. Queue-based scaling adds workers automatically when
requests pile up. Network volumes share the model across all workers. Can scale to
dozens of concurrent reviews.

## Cost Estimates Per Review

Assuming ~3 minutes of GPU time per review (model load + inference):

| Platform | GPU | Cost Per Review | Notes |
|---|---|---|---|
| Vast.ai | A100 | ~$0.02-0.05 | Plus ~3-5 min cold start overhead |
| Modal | A100 80GB | ~$0.13 | With GPU snapshots, ~5s cold start |
| Modal | H100 | ~$0.20 | With GPU snapshots, ~5s cold start |
| RunPod | A100 (flex) | ~$0.14 | With FlashBoot, 0.5-30s cold start |
| RunPod | H100 (flex) | ~$0.21 | With FlashBoot, 0.5-30s cold start |

Vast.ai is cheapest per-review but has the highest cold start overhead. Modal and RunPod
are comparable in cost and offer much faster cold starts. For sporadic use where you can
tolerate a few minutes of setup, Vast.ai wins on price. For anything interactive, Modal
or RunPod are the better choice.
