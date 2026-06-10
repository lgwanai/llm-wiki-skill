# RAG (Retrieval-Augmented Generation)

Retrieval-Augmented Generation combines information retrieval with text generation to ground LLM outputs in external knowledge. First popularized by Lewis et al. (2020), RAG has become a standard pattern for building knowledge-grounded AI applications.

## Core Pipeline

### 1. Document Processing
Documents are chunked into smaller segments (typically 256-1024 tokens) with overlap to preserve context across chunk boundaries. Common chunking strategies include:
- **Fixed-size chunking**: Split every N tokens with M-token overlap
- **Semantic chunking**: Split at natural boundaries like paragraphs or sections
- **Recursive chunking**: Hierarchically split into increasingly smaller chunks

### 2. Embedding & Indexing
Each chunk is converted to a dense vector embedding using models like OpenAI text-embedding-3 or open-source alternatives (BGE, E5, Jina). These embeddings are stored in a vector database (Pinecone, Weaviate, Milvus, FAISS) for efficient similarity search.

### 3. Retrieval
At query time, the query is embedded and used to find the most similar document chunks via approximate nearest neighbor (ANN) search. Common improvements include:
- **Hybrid search**: Combine dense (vector) and sparse (BM25) retrieval
- **Re-ranking**: Apply a cross-encoder to re-score top candidates
- **Query rewriting**: Expand or decompose the user's query for better recall

### 4. Generation
Retrieved chunks are inserted into the LLM's context window alongside the user's query. The model generates a response grounded in the provided context. Citations can be generated to attribute claims to specific sources.

## Common Failure Modes

### Hallucination Despite Context
The LLM may generate information not present in the retrieved context, especially when the context is insufficient or the model over-relies on its parametric knowledge.

### Retrieval Failure
The correct document chunk may not be retrieved due to:
- Query-document vocabulary mismatch (the "lexical gap")
- Poor chunking that breaks key information across boundaries
- Embedding model not capturing domain-specific semantics

### Context Pollution
Too many irrelevant chunks dilute the model's attention, causing it to miss key information (the "lost in the middle" problem). Most models attend best to the beginning and end of the context window.

### Citation Errors
When citations are generated, they may point to wrong sources or fail to cover all factual claims. Citation precision and recall metrics are important for high-stakes applications.

## Advanced RAG Patterns

### GraphRAG
Uses knowledge graphs to capture entity relationships. Retrieval traverses the graph to find related information beyond simple text similarity. Microsoft's GraphRAG uses LLM-generated community summaries over entity relationship graphs.

### Agentic RAG
The LLM acts as an agent that can issue multiple retrieval calls, refine queries, and decide when it has enough information. This is more flexible but adds latency and cost.

### Self-RAG
The model learns to retrieve on-demand and critique its own generations, deciding when retrieval is needed and whether retrieved passages are relevant.

## Evaluation

### RAGAS Framework
RAGAS evaluates RAG systems on:
- **Faithfulness**: Is the answer grounded in the provided context?
- **Answer Relevance**: Does the answer address the question?
- **Context Precision**: Are retrieved documents relevant?
- **Context Recall**: Are all relevant documents retrieved?

### Other Metrics
- **BLEU/ROUGE**: N-gram overlap with reference answers (poor for RAG due to valid paraphrasing)
- **Human Evaluation**: Gold standard but expensive
- **LLM-as-Judge**: Using a strong LLM to score outputs

## References
- Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", NeurIPS 2020
- Gao et al., "RAGAS: Automated Evaluation of Retrieval Augmented Generation", 2024
- Edge et al., "From Local to Global: A Graph RAG Approach to Query-Focused Summarization", 2024
