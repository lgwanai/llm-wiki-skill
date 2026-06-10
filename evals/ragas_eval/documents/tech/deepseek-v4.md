# DeepSeek-V4 Architecture Overview

DeepSeek-V4 is a large language model released in 2025 by DeepSeek-AI. It uses a Mixture-of-Experts (MoE) architecture with several key innovations aimed at efficient inference.

## Architecture Design

### Multi-head Latent Attention (MLA)
MLA compresses keys and values into a low-rank latent space before attention computation, dramatically reducing the KV-cache size during inference. For a 128K context window, standard multi-head attention requires ~256GB of KV-cache, while MLA reduces this to ~32GB.

The compression works by projecting key-value pairs through a low-rank bottleneck:
```
c = W_d * h           # Down-projection (d << d_model)
k = W_uk * c          # Up-projection for keys
v = W_uv * c          # Up-projection for values
```

### DeepSeekMoE
Fine-grained expert segmentation with shared expert isolation:
- 256 total experts, each with ~25M parameters
- 8 experts activated per token (top-8 routing)
- 2 shared experts always activated
- Load balancing loss ensures uniform expert utilization
- Device-level auxiliary loss for distributed training

### Training Configuration
- Total parameters: 685B (including all experts)
- Active parameters per token: ~37B
- Training data: 14.8T tokens
- Context length: 128K tokens (native, not extrapolated)
- Vocabulary: 129,280 tokens (byte-level BPE)

## Performance

### Benchmarks
| Benchmark | Score |
|-----------|-------|
| MMLU | 89.1 |
| MATH-500 | 92.3 |
| HumanEval | 94.8 |
| GSM8K | 95.7 |
| MMLU-Pro | 78.5 |

### Inference Efficiency
- KV-cache compression ratio: 8x vs standard MHA
- Expert load balance: 99.2% utilization
- Time-to-first-token: 0.8s (8-GPU node)
- Generation throughput: 3200 tokens/s (8-GPU node)

## Comparison with Other Models

DeepSeek-V4 achieves comparable performance to GPT-4o and Claude 3.5 Sonnet on most benchmarks while using a more efficient architecture. Its MoE design means only 37B of 685B parameters are active per token, making it more compute-efficient than dense models of similar capability.

## Limitations

- Requires significant GPU memory to load all experts (8x A100-80GB minimum)
- MoE routing can cause expert collapse if load balancing is not carefully tuned
- MLA's low-rank compression may lose fine-grained information for certain tasks
- Does not support native multimodal input (text only)

## References
- DeepSeek-AI, "DeepSeek-V4 Technical Report", 2025
- Dai et al., "DeepSeekMoE: Towards Ultimate Expert Specialization", 2024
