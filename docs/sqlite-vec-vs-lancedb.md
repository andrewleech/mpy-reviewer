# sqlite-vec vs LanceDB for mpy-reviewer

Analysis performed 2026-02-20 against the current dataset (18,614 records, 768-dim CodeRankEmbed vectors) on WSL2 with 45 GB RAM and a 15 GB remote host (nug).

## Performance comparison (18,614 records, 768-dim)

| Metric | sqlite-vec | LanceDB |
|---|---|---|
| Install size | 164 KB | ~286 MB |
| Storage on disk | ~61 MB | 1.4 GB |
| Memory (querying) | ~47 MB | ~498 MB |
| KNN query latency | 16 ms | 553 ms |
| Hybrid search (FTS + KNN) | 40 ms | ~1000 ms |
| Filtered KNN | 10 ms | ~500 ms |
| FTS only | 2 ms (FTS5) | not separately measured |

## sqlite-vec pros

- **35x faster queries** -- brute-force on 18K 768-dim vectors is trivially fast at this scale.
- **1,700x smaller dependency** -- 164 KB vs 286 MB installed. Uses stdlib `sqlite3`, no pyarrow/pydantic/lance chain.
- **23x smaller storage** -- 61 MB vs 1.4 GB for the same data.
- **10x less RAM** -- stays flat at ~47 MB vs LanceDB's 498 MB (with documented memory leak issues in LanceDB GitHub #2512, #2468).
- **Merges into existing `reviews.db`** -- eliminates the separate Lance directory entirely. Vectors, FTS5, and metadata live in one file with JOINs to existing tables (`prs`, `review_comments`, `comment_categories`).
- **Hybrid search in pure SQL** -- FTS5 + vec0 combined via CTEs with RRF in a single query. No Python fusion code needed (replaces `_reciprocal_rank_fusion` in retriever.py). See [Alex Garcia's hybrid search post](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html).
- **Battle-tested FTS5** -- vs LanceDB's FTS which is mid-transition from Tantivy to native, with documented bugs and limitations (no phrase queries, no incremental indexing, `where` clause bugs with scalar indexes per GitHub #1656).
- **Solves the nug OOM problem** -- 47 MB vs 498 MB makes a real difference on a 15 GB machine.

## sqlite-vec cons

- **Brute-force only** -- no ANN indexes (IVF/HNSW planned but timeline has slipped past the original Dec 2024/Jan 2025 target). Irrelevant at 20K vectors; becomes a concern above ~250K at 768 dims.
- **No versioning/time-travel** -- LanceDB has this built in (unused in this project).
- **Raw SQL API** -- no fluent `.search().where().limit()` chain; queries are SQL strings. More verbose but also more flexible (CTEs, JOINs, subqueries, window functions).
- **Pre-v1, single maintainer** -- Alex Garcia, Mozilla-sponsored. ~7K GitHub stars. Breaking changes expected.
- **Metadata filter gaps** -- no `LIKE`, `GLOB`, `NULL` support in vec0 WHERE clauses yet. Not needed for current filters which are all equality checks on categorization fields.

## LanceDB pros

- **Fluent Python API** -- `.search(vec).where("domain = 'x'").limit(10).to_list()` is readable.
- **ANN indexes** -- IVF_PQ available if dataset grows to millions.
- **Built-in versioning** -- time-travel queries on table state.
- **VC-funded company** -- larger team, more contributors, ~12K GitHub stars.

## LanceDB cons

- **Heavy dependency chain** -- pyarrow (154 MB), pydantic (9.4 MB), lance-namespace (4 MB), plus transitive deps. ~286 MB total installed.
- **Memory leaks** -- multiple open GitHub issues (#2512, #2468), RSS grows with repeated queries. Observed 498 MB for simple query workloads on 18K records.
- **FTS in transition** -- Tantivy being replaced with native Lance FTS. Current version: no phrase queries, no incremental indexing, no tokenizer customization, `where` clause bugs with scalar indexes (#1656).
- **1.4 GB storage** for 18K records due to columnar format overhead, versioning metadata, and transaction logs.
- **Frequent breaking changes** -- still "Alpha" on PyPI despite version 0.29. API churn across releases.
- **OOM'd on nug** -- CUDA torch + LanceDB memory combo killed the build process on a 15 GB machine.

## Migration surface

Only 4 files import lancedb directly:

| File | Operations used |
|---|---|
| `rag/indexer.py` | connect, create_table, open_table, add, create_fts_index, len |
| `rag/retriever.py` | search (dense), search (FTS), where, limit, to_list |
| `scripts/build_index_resume.py` | connect, create_table, open_table, add, to_pandas, create_fts_index |
| `scripts/add_fts_index.py` | connect, open_table, create_fts_index, len |

The `ReviewRetriever` class already abstracts all search behind a clean API. The rest of the codebase (CLI, MCP server, prompt builder, graph expander, reranker) uses the retriever abstraction and never touches LanceDB directly. ~13% of project files have direct LanceDB access.

The RRF fusion currently implemented in Python (`_reciprocal_rank_fusion`) could move into a single SQL CTE query combining FTS5 BM25 scores with vec0 distances.

## sqlite-vec API pattern

```python
import sqlite3, sqlite_vec

db = sqlite3.connect("data/reviews.db")
db.enable_load_extension(True)
sqlite_vec.load(db)

# Hybrid search with RRF in a single query
results = db.execute("""
    WITH fts_results AS (
        SELECT rowid, rank AS score
        FROM review_fts WHERE review_fts MATCH ?
        ORDER BY rank LIMIT ?
    ),
    vec_results AS (
        SELECT rowid, distance AS score
        FROM vec_reviews WHERE embedding MATCH ? AND k = ?
    ),
    rrf AS (
        SELECT rowid,
            COALESCE(1.0 / (60 + fts_rank), 0) +
            COALESCE(1.0 / (60 + vec_rank), 0) AS rrf_score
        FROM (
            SELECT COALESCE(f.rowid, v.rowid) AS rowid,
                ROW_NUMBER() OVER (ORDER BY f.score) AS fts_rank,
                ROW_NUMBER() OVER (ORDER BY v.score) AS vec_rank
            FROM fts_results f FULL OUTER JOIN vec_results v
                ON f.rowid = v.rowid
        )
        ORDER BY rrf_score DESC LIMIT ?
    )
    SELECT r.*, c.domain, c.severity, c.body
    FROM rrf r JOIN comment_categories c ON r.rowid = c.rowid
""", [query_text, top_k, serialize_float32(query_vec), top_k, final_k]).fetchall()
```

## Assessment

At 18,614 records with 768 dimensions, sqlite-vec is the better fit. The brute-force limitation is irrelevant below ~250K vectors. Storing everything in `reviews.db` eliminates data duplication, simplifies deployment (one file vs a 1.4 GB directory), and drops the dependency footprint from 286 MB to 164 KB. The memory and performance characteristics would have avoided the OOM on nug.

## References

- [sqlite-vec GitHub](https://github.com/asg017/sqlite-vec)
- [sqlite-vec documentation](https://alexgarcia.xyz/sqlite-vec/)
- [sqlite-vec hybrid search with FTS5](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html)
- [sqlite-vec metadata columns](https://alexgarcia.xyz/blog/2024/sqlite-vec-metadata-release/index.html)
- [sqlite-vec v0.1.0 benchmarks](https://alexgarcia.xyz/blog/2024/sqlite-vec-stable-release/index.html)
- [sqlite-vec ANN tracking issue](https://github.com/asg017/sqlite-vec/issues/25)
- [LanceDB memory issue #2512](https://github.com/lancedb/lancedb/issues/2512)
- [LanceDB memory leak #2468](https://github.com/lancedb/lancedb/issues/2468)
- [LanceDB FTS where clause bug #1656](https://github.com/lancedb/lancedb/issues/1656)
- [Simon Willison on sqlite-vec hybrid search](https://simonwillison.net/2024/Oct/4/hybrid-full-text-search-and-vector-search-with-sqlite/)
