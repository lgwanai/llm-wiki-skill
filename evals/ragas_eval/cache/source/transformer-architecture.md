# Transformer Architecture

The Transformer architecture, introduced in "Attention Is All You Need" (Vaswani et al., 2017), is the foundation of modern large language models. It replaces recurrent neural networks with a pure attention mechanism.

## Key Components

### Multi-Head Self-Attention
The core innovation is scaled dot-product attention:

```
Attention(Q, K, V) = softmax(QK^T / sqrt(d_k)) * V
```

Multi-head attention runs multiple attention heads in parallel, each with different learned projections. Each head can attend to different aspects of the input, allowing the model to capture diverse relationships.

### Position Encoding
Since the Transformer has no recurrence, it needs explicit position information. The original paper uses sinusoidal position encodings:

```
PE(pos, 2i) = sin(pos / 10000^(2i/d_model))
PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))
```

Modern implementations often use learned position embeddings or rotary position embeddings (RoPE).

### Feed-Forward Networks
Each Transformer block contains a position-wise feed-forward network with two linear transformations and a GELU activation. The standard hidden dimension is 4x the model dimension, giving FFNs roughly 2/3 of the total parameters.

## Architecture Variants

### Encoder-Decoder
The original Transformer has both encoder and decoder stacks. The encoder processes the input sequence bidirectionally, while the decoder generates output autoregressively with causal masking.

### Decoder-Only (GPT-style)
Modern LLMs use decoder-only architectures where every token can only attend to previous tokens (causal attention). This simplifies the architecture and is more efficient for autoregressive generation. GPT-3, GPT-4, and DeepSeek-V4 all use decoder-only designs.

### Encoder-Only (BERT-style)
BERT uses only the encoder stack with bidirectional attention, optimized for understanding tasks like classification and named entity recognition. It uses masked language modeling (MLM) as its pre-training objective.

## Training

### Pre-training Objectives
- **Causal Language Modeling (CLM)**: Predict the next token given previous tokens. Used by GPT-style models.
- **Masked Language Modeling (MLM)**: Predict masked tokens from bidirectional context. Used by BERT.
- **Prefix Language Modeling**: A hybrid approach where a prefix is encoded bidirectionally and the suffix is generated autoregressively.

### Scaling Laws
The Chinchilla scaling law (Hoffmann et al., 2022) established that optimal training requires roughly 20 tokens per parameter. For a 7B parameter model, this means training on approximately 140B tokens. Most modern models are "over-trained" relative to Chinchilla-optimal, trading more training compute for better inference efficiency.

## Key Innovations Since 2017

1. **Rotary Position Embedding (RoPE)**: Encodes position information through rotation matrices, enabling better length generalization (Su et al., 2021).

2. **Flash Attention**: IO-aware attention algorithm that reduces memory usage from O(N^2) to O(N) by tiling the attention computation (Dao et al., 2022).

3. **Grouped Query Attention (GQA)**: Shares key-value heads across query heads to reduce KV-cache memory during inference (Ainslie et al., 2023).

4. **Mixture of Experts (MoE)**: Routes tokens to different expert FFN sub-networks, enabling much larger models without proportional compute increase (Shazeer et al., 2017). DeepSeek-V2 and V4 use DeepSeekMoE with finer-grained experts and shared experts.

5. **Multi-head Latent Attention (MLA)**: DeepSeek's innovation that compresses KV-cache into a low-rank latent space, dramatically reducing inference memory (DeepSeek-AI, 2024).

## References
- Vaswani et al., "Attention Is All You Need", NeurIPS 2017
- Brown et al., "Language Models are Few-Shot Learners", NeurIPS 2020
- Hoffmann et al., "Training Compute-Optimal Large Language Models", NeurIPS 2022
