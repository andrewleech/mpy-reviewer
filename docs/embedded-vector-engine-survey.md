# Embedded Vector Search Engine Survey

Researched 2026-02-20. Evaluated as potential replacements for LanceDB in the mpy-reviewer project (18,614 records, 768-dim CodeRankEmbed vectors, hybrid dense+FTS search with metadata filtering).

**Hard requirements:** embeddable (in-process, no separate service/daemon/docker), vector similarity search on 768-dim float32, persistent storage. Python preferred but not required.

## Summary table

| Engine | Embeddable | FTS | Metadata Filter | Hybrid Native | Dep Weight | Persistence | Stars | Maturity |
|---|---|---|---|---|---|---|---|---|
| **LanceDB** (current) | Yes | Yes (Tantivy) | Yes | Yes | Heavy (~286 MB) | Yes (Lance dir) | 9.0K | Alpha (v0.29) |
| **sqlite-vec** | Yes | Via FTS5 | Partition keys + WHERE | Via SQL+RRF | Zero (164 KB) | Yes (SQLite) | 7.0K | Pre-v1 |
| **USearch** | Yes | No | Callbacks only | No | Zero (< 1 MB) | Yes (mmap) | 3.9K | Stable |
| **Qdrant local** | Yes | Yes (basic) | Excellent | Yes | Light (~390 KB) | Yes | 1.2K | Local = Python reimpl |
| **txtai** | Yes | Yes (BM25) | Yes (SQL-like) | Yes | Heavy but overlapping | Yes | 12.2K | Mature |
| **FAISS** | Yes | No | Minimal | No | Moderate (BLAS) | File save/load | 39.1K | Very mature |
| **Chroma** | Yes | Substring only | Yes (rich) | Partial | Very heavy | Yes | 26.2K | Stable |
| **DuckDB+VSS** | Yes | Yes (BM25) | Not with index | Via SQL | Moderate (~40 MB) | Yes | 36.2K | Experimental |
| **Tantivy** | Yes | Excellent | Yes (schema) | FTS only | Moderate (Rust) | Yes | 14.6K | Mature |
| **Zvec** | Yes | Scalar inverted | Yes | Yes (fusion+RRF) | Moderate (C++) | Yes | 5.2K | v0.2, weeks old |
| **Annoy** | Yes | No | No | No | Minimal | mmap | 14.2K | Deprecated |
| **Voyager** | Yes | No | No | No | Minimal | File save/load | 1.5K | Slowing |
| **Typesense** | **No (server)** | Yes | Yes | Yes | N/A | N/A | N/A | N/A |
| **OpenRAG** | **No (app stack)** | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

## Detailed evaluations

### OpenRAG

**Not applicable.** OpenRAG is an AGPL-licensed modular RAG application platform with web UIs (Chainlit chat, FastAPI), Milvus as its vector backend, Ray for distributed processing, and Kubernetes deployment. It is a multi-service application stack, not an embeddable library. The mpy-reviewer project already has its own RAG pipeline; replacing LanceDB with an entire RAG framework is not what's needed.

### Chroma (chromadb)

- **Version:** 1.5.1, Apache-2.0, 26.2K stars, very active
- **Embeddable:** Yes. `chromadb.PersistentClient(path=...)` runs in-process.
- **Storage:** SQLite for metadata + HNSW binary files on disk.
- **Vector search:** HNSW (Rust-based hnswlib). Cosine, L2, inner product.
- **FTS:** Substring/regex matching only (`$contains`, `$regex`). Not BM25-ranked. Open issue requesting BM25 hybrid search (#1686).
- **Metadata filtering:** Rich `where` clause with `$eq`, `$ne`, `$gt`, `$lt`, `$in`, `$nin`, `$and`, `$or`.
- **Hybrid search:** Partial. Vector + metadata filtering works. Vector + true ranked FTS does not exist.
- **Dependencies:** Very heavy. Pulls `onnxruntime`, `grpcio`, `kubernetes`, `protobuf`, `opentelemetry-*`, `posthog`, `uvicorn`, `httptools`, `flatbuffers`, and ~30 other transitive deps.
- **Assessment:** Strong metadata filtering but weak FTS (substring, not ranked). The dependency footprint is worse than LanceDB. Not an improvement for this project.

### Qdrant (local mode)

- **Version:** client v1.17.0, Apache-2.0, active
- **Embeddable:** Yes. `QdrantClient(path="./qdrant_data")` runs in-process.
- **Storage:** Disk-backed JSON/binary files.
- **Vector search:** HNSW. Cosine, Euclidean, Dot product.
- **FTS:** Yes, with tokenization. In local mode this is a pure-Python reimplementation, not the Rust engine.
- **Metadata filtering:** The strongest of any option. Payload filtering with `must`, `should`, `must_not` conditions. Supports nested fields, ranges, geo, keyword match.
- **Hybrid search:** Yes, combining vector search with FTS and payload filtering.
- **Dependencies:** Light. Client wheel is 390 KB. Deps are `httpx`, `grpcio`, `pydantic`, `numpy` — most already in the project.
- **Assessment:** Feature-rich and light. The concern is that local mode is a **pure-Python reimplementation** of the Qdrant Rust engine, not the actual engine. Feature parity may lag behind the server version. At 20K vectors performance is fine regardless. The API is well-designed — same interface for local and server modes.

### FAISS (faiss-cpu)

- **Version:** 1.13.2, MIT, 39.1K stars, very active
- **Embeddable:** Yes. Pure library.
- **Storage:** `faiss.write_index()` / `faiss.read_index()` to flat files. No built-in database.
- **Vector search:** The gold standard. Flat, IVF, HNSW, PQ, SQ, and composites. L2, inner product, cosine.
- **FTS:** None.
- **Metadata filtering:** Minimal. IDSelector callbacks for filtering during search, but no metadata store.
- **Hybrid search:** None. Must build manually.
- **Dependencies:** Moderate. Numpy + bundled BLAS (MKL or OpenBLAS).
- **Assessment:** Best vector indexing algorithms available, but purely a vector index — no metadata, no FTS, no persistence abstraction. Using FAISS directly means building all the database functionality yourself. Only makes sense if you need very specific index types. At 20K vectors, flat (exact) search is < 10 ms, so ANN indexing is unnecessary.

### USearch (Unum)

- **Version:** 2.23.0, Apache-2.0, 3.9K stars, active
- **Embeddable:** Yes. Single C++11 header (~3000 lines). Python bindings via pybind11.
- **Storage:** `index.save()` / `index.load()`. Memory-mapped serving from disk.
- **Vector search:** HNSW. Cosine, L2, inner product, Hamming, user-defined metrics with JIT. f32, f16, i8 vectors. Claims 10x faster than FAISS HNSW.
- **FTS:** None (listed as "coming soon").
- **Metadata filtering:** Via predicate callbacks during HNSW traversal. Can integrate external filters but no built-in metadata store.
- **Hybrid search:** None natively.
- **Dependencies:** Zero. The < 1 MB wheel is self-contained.
- **Assessment:** The lightest-weight vector index library available. Zero dependencies, < 1 MB, fast, disk persistence with mmap. The callback-based filtering during HNSW traversal is a feature FAISS lacks. Like FAISS, it's purely a vector index — needs pairing with SQLite FTS5 or tantivy for full-text search. The integration work to build a complete hybrid search system is significant.

### txtai

- **Version:** 9.5.0, Apache-2.0, 12.2K stars, active
- **Embeddable:** Yes. Runs in-process. Can also deploy as API server.
- **Storage:** SQLite for metadata, FAISS or other backends for vectors. Persists to disk.
- **Vector search:** Via FAISS, Annoy, or Hnswlib backends. Configurable.
- **FTS:** Yes. Built-in BM25 scoring via SQLite FTS.
- **Metadata filtering:** Yes. SQL-like queries: `SELECT * FROM txtai WHERE similarity > 0.7 AND field = 'value'`.
- **Hybrid search:** Yes. Dense + sparse (BM25) retrieval with configurable fusion.
- **Dependencies:** Heavy standalone, but overlaps significantly with this project's existing deps (torch, transformers, sentence-transformers).
- **Assessment:** Most feature-complete option for out-of-the-box hybrid search with metadata filtering. The SQL-like query interface is compelling. Claims 3x faster than Chroma. The risk is framework lock-in — the existing custom retrieval pipeline (heuristic boosting, MMR diversity, graph expansion) would need to adapt to txtai's architecture, or txtai would need to be used as a low-level component.

### Tantivy (via tantivy-py)

- **Version:** 0.25.1, MIT, 14.6K stars (Rust), active
- **Embeddable:** Yes. Rust library with PyO3 bindings.
- **Storage:** Directory on disk (segment files).
- **Vector search:** None. Pure full-text search engine.
- **FTS:** Excellent. BM25 scoring, tokenization, stemming, fuzzy search, faceted search, filters. Comparable to Lucene.
- **Metadata filtering:** Yes. Schema-based fields with range, term, and boolean queries.
- **Assessment:** Not a LanceDB replacement on its own. Relevant as a component: **sqlite-vec + tantivy-py** or **USearch + tantivy-py** for production-quality BM25 FTS paired with a vector index. Maintained by Quickwit (the company behind tantivy). The strongest FTS option available.

### DuckDB with VSS extension

- **Version:** DuckDB 1.4.4, MIT, 36.2K stars, very active
- **Embeddable:** Yes. Designed as an embedded analytical database.
- **Storage:** Native database files on disk.
- **Vector search:** Via `vss` extension. HNSW. L2, cosine, inner product. **Experimental.**
- **FTS:** Via `fts` extension. BM25-based. **Also experimental.**
- **Metadata filtering:** Full SQL, but **the HNSW index cannot be combined with WHERE clauses**. Vector search and metadata filtering cannot happen in a single index scan — requires search-then-filter.
- **Assessment:** Both extensions are explicitly experimental and not recommended for production. The WHERE clause limitation is a blocker. DuckDB is worth watching for future versions but not ready for this use case.

### Zvec (Alibaba)

- **Version:** 0.2.0, Apache-2.0, 5.2K stars, announced Feb 2026
- **Embeddable:** Yes. In-process, C++ core with Python bindings (SWIG).
- **Storage:** Disk-backed.
- **Vector search:** Dense and sparse. Built on Alibaba's Proxima engine.
- **Metadata filtering:** Yes. Scalar filters pushed into index execution path.
- **Hybrid search:** Yes. Built-in RRF and weighted fusion.
- **Platforms:** Linux x86_64/ARM64, macOS ARM64. Python 3.10-3.12 only. No Windows.
- **Assessment:** Feature set maps well to this project's needs. Risks: v0.2 (weeks old), no Python 3.13/3.14 support, limited platform coverage, unknown maintenance trajectory. Too new for production reliance. Worth monitoring.

### Annoy (Spotify)

- **Version:** 1.17.3, Apache-2.0, 14.2K stars, last commit Oct 2025
- **Assessment:** Effectively deprecated by Spotify in favor of [Voyager](https://github.com/spotify/voyager). Read-only after build (no incremental updates), no metadata, no FTS. Not viable.

### Voyager (Spotify)

- **Version:** 2.1.0, Apache-2.0, 1.5K stars, last commit Sep 2025
- **Assessment:** Annoy's successor. Fast HNSW, lightweight, but purely a vector index — no metadata, no FTS. Commit activity has slowed. Same category as USearch but less active.

### Typesense

- **Assessment:** Server-only. Runs as a separate daemon communicating via HTTP. No in-process library mode. Does not meet the embeddable requirement.

## Recommended strategies (ranked)

### 1. sqlite-vec + SQLite FTS5

Unify vector search into the existing `reviews.db`. Vectors, FTS5, and metadata in one file with JOINs to existing tables. Hybrid search via RRF in SQL. Zero new dependencies. Brute-force KNN is fast enough at 20K vectors (~16 ms). Eliminates pyarrow and LanceDB from the dep tree, drops storage from 1.4 GB to ~61 MB. See [separate analysis](sqlite-vec-vs-lancedb.md).

### 2. USearch + SQLite FTS5

USearch for the vector index (< 1 MB, zero deps, mmap, HNSW) paired with SQLite FTS5 for full-text search. Store metadata in SQLite. Implement RRF fusion in Python. Gives production-quality ANN search with minimal footprint. More glue code than option 1. The predicate callback during HNSW traversal enables efficient pre-filtering.

### 3. Qdrant local mode

Drop-in replacement with the richest feature set out of the box. Light dependency footprint (~390 KB). Local mode is a pure-Python reimplementation, not the Rust engine — feature parity may lag. Good API design.

### 4. txtai

Hybrid search framework with BM25 + dense retrieval, metadata filtering, persistence. High dependency overlap with existing project. Risk of framework lock-in conflicting with custom retrieval pipeline (heuristic boosting, MMR diversity, graph expansion).

### Not recommended

- **OpenRAG** — wrong category (application stack, not a library)
- **Typesense** — server-only
- **Chroma** — worse dependency footprint than LanceDB, weak FTS
- **DuckDB+VSS** — experimental, WHERE clause limitation
- **Annoy** — deprecated by its creators
- **Voyager** — vector-only, activity slowing
- **Zvec** — too new (v0.2, weeks old), no Python 3.13+

## References

- [sqlite-vec GitHub](https://github.com/asg017/sqlite-vec)
- [sqlite-vec hybrid search](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html)
- [USearch GitHub](https://github.com/unum-cloud/USearch)
- [Chroma GitHub](https://github.com/chroma-core/chroma)
- [Qdrant Client GitHub](https://github.com/qdrant/qdrant-client)
- [FAISS GitHub](https://github.com/facebookresearch/faiss)
- [txtai GitHub](https://github.com/neuml/txtai)
- [tantivy-py GitHub](https://github.com/quickwit-oss/tantivy-py)
- [DuckDB VSS docs](https://duckdb.org/docs/stable/core_extensions/vss)
- [Zvec GitHub](https://github.com/alibaba/zvec)
- [Spotify Voyager](https://github.com/spotify/voyager)
- [Spotify Annoy](https://github.com/spotify/annoy)
- [Simon Willison on sqlite-vec hybrid search](https://simonwillison.net/2024/Oct/4/hybrid-full-text-search-and-vector-search-with-sqlite/)
