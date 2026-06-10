# Vector Database Comparison

Vector databases store high-dimensional embedding vectors and enable efficient similarity search. They are a critical component of RAG systems.

## Key Algorithms

### HNSW (Hierarchical Navigable Small World)
A graph-based algorithm that builds a multi-layer navigation structure. Search traverses from top layers (long-range edges) to bottom layers (local edges). HNSW offers ~95%+ recall with logarithmic search time. Parameters: M (edges per node, default 16), efConstruction (build quality, default 200), efSearch (search quality).

### IVF (Inverted File Index)
Partitions vectors into clusters using k-means. At query time, only the nearest clusters are searched. IVF significantly reduces search scope at the cost of some recall. Parameters: nlist (number of clusters), nprobe (clusters to search).

### ScaNN (Scalable Nearest Neighbors)
Google's vector quantization approach that compresses vectors and applies anisotropic weighting for better distance preservation. Achieves 2-3x throughput improvement over HNSW at similar recall levels.

## Major Vector Databases

| Database | Architecture | Strengths | Weaknesses |
|----------|-------------|-----------|------------|
| **Pinecone** | Managed cloud | Zero-ops, serverless, good defaults | Expensive at scale, limited control |
| **Weaviate** | Open-source + cloud | GraphQL API, hybrid search built-in | Complex schema management |
| **Milvus** | Open-source + cloud | High throughput, GPU acceleration | Heavy infrastructure requirements |
| **Qdrant** | Open-source + cloud | Rust performance, rich filtering | Smaller ecosystem |
| **FAISS** | Library (Meta) | Fastest single-node, GPU support | No persistence, no filtering, library not a database |
| **Chroma** | Open-source | Simple, developer-friendly | Limited scale, single-node only |

## Performance Trade-offs

### Recall vs. Latency
Higher recall requires searching more candidates, increasing latency. Typical production targets: 95% recall@10, p99 < 100ms.

### Memory vs. Speed
Vector compression (PQ, SQ, scalar quantization) reduces memory by 4-32x but reduces recall by 1-5%. Disk-resident indexes (DiskANN) trade latency (10-50ms) for nearly unlimited capacity.

### Filtering
Pre-filtering (apply metadata filter before vector search) is simpler but may miss candidates. Post-filtering guarantees correct results but requires fetching more candidates. Hybrid filtering combines both.

## Production Recommendations

For RAG systems handling < 1M documents:
- FAISS for single-node, cost-optimized deployments
- Qdrant or Weaviate for multi-user, filtered search

For systems handling > 10M documents:
- Milvus with GPU acceleration
- Pinecone serverless for hands-off scaling

## References
- Malkov & Yashunin, "Efficient and Robust Approximate Nearest Neighbor Search Using HNSW", 2018
- Johnson et al., "Billion-Scale Similarity Search with GPUs", 2019 (FAISS paper)
- Guo et al., "Accelerating Large-Scale Inference with ScaNN", 2020
