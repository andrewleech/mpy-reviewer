#!/usr/bin/env python3
"""Extract common review patterns from the mpy-reviewer RAG database.

Clusters categorized review comments by (domain, language_context) strata
using HDBSCAN, then ranks clusters by importance to produce a checklist
for MicroPython PR authors.
"""

import json
import logging
import os
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import log
from pathlib import Path
from typing import Optional

import click
import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.metrics.pairwise import cosine_similarity
from tqdm import tqdm

# Add project root to path so we can import rag.*
sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.config import get_config
from rag.indexer import get_vec_connection, _VEC_META_COLS, _VEC_AUX_COLS

logger = logging.getLogger(__name__)

# Theme substrings to exclude (process/notification noise).
_THEME_EXCLUDE = ["merge", "acknowledg", "notification", "superseded", "approval"]

# Claude CLI timeout for checklist generation.
_LLM_TIMEOUT_SECONDS = 120

# JSON schema for Claude CLI structured output.
_CHECKLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "checklist": {
                        "type": "string",
                        "description": "Imperative sentence for a checklist item",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "1-2 sentence explanation of why this matters",
                    },
                    "applies_to": {
                        "type": "string",
                        "description": "Scope: which files/areas this applies to",
                    },
                },
                "required": ["checklist", "explanation", "applies_to"],
            },
        }
    },
    "required": ["items"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ClusterRecord:
    """A single review record with its embedding and metadata."""

    rowid: int
    embedding: np.ndarray
    meta: dict


@dataclass
class Cluster:
    """A cluster of related review comments."""

    cluster_id: int
    stratum: tuple  # (domain, language_context)
    records: list  # list of ClusterRecord

    # Computed after construction
    centroid: Optional[np.ndarray] = None
    frequency: int = 0
    severity_counts: dict = field(default_factory=dict)
    importance: float = 0.0
    component_counts: dict = field(default_factory=dict)
    top_keywords: list = field(default_factory=list)
    top_themes: list = field(default_factory=list)
    representative_examples: list = field(default_factory=list)

    # Filled by LLM or heuristic
    checklist_text: str = ""
    explanation_text: str = ""
    applies_to: str = ""

    def compute_stats(self):
        """Compute all derived statistics from records."""
        self.frequency = len(self.records)

        # Centroid
        embeddings = np.stack([r.embedding for r in self.records])
        self.centroid = embeddings.mean(axis=0)

        # Severity distribution
        sev_counter = Counter(r.meta.get("severity", "suggestion") for r in self.records)
        self.severity_counts = dict(sev_counter)

        # Importance score
        b = sev_counter.get("blocking", 0)
        s = sev_counter.get("suggestion", 0)
        n = sev_counter.get("nitpick", 0)
        self.importance = (b * 3.0 + s * 1.5 + n * 0.5) * log(1 + self.frequency)

        # Component distribution
        comp_counter = Counter(
            r.meta.get("component", "unknown")
            for r in self.records
            if r.meta.get("component")
        )
        self.component_counts = dict(comp_counter)

        # Top keywords (from JSON keywords field)
        kw_counter = Counter()
        for r in self.records:
            kw_raw = r.meta.get("keywords")
            if kw_raw:
                try:
                    kws = json.loads(kw_raw) if isinstance(kw_raw, str) else kw_raw
                    for kw in kws:
                        kw_counter[kw.lower()] += 1
                except (json.JSONDecodeError, TypeError):
                    pass
        self.top_keywords = [kw for kw, _ in kw_counter.most_common(8)]

        # Top themes (3 most common)
        theme_counter = Counter(
            r.meta.get("theme", "") for r in self.records if r.meta.get("theme")
        )
        self.top_themes = [t for t, _ in theme_counter.most_common(3)]

        # Representative examples
        self._pick_representatives(embeddings)

    def _pick_representatives(self, embeddings: np.ndarray):
        """Pick up to 3 representative examples."""
        examples = []

        # 1. Closest to centroid
        centroid_2d = self.centroid.reshape(1, -1)
        sims = cosine_similarity(centroid_2d, embeddings)[0]
        closest_idx = int(np.argmax(sims))
        examples.append(("centroid", self.records[closest_idx]))

        # 2. Highest severity comment
        severity_order = {"blocking": 3, "suggestion": 2, "nitpick": 1}
        highest_sev_idx = max(
            range(len(self.records)),
            key=lambda i: severity_order.get(
                self.records[i].meta.get("severity", "nitpick"), 0
            ),
        )
        if highest_sev_idx != closest_idx:
            examples.append(("highest_severity", self.records[highest_sev_idx]))

        # 3. One with code suggestion (if any, and not already picked)
        picked_rowids = {ex[1].rowid for ex in examples}
        for r in self.records:
            if r.meta.get("has_code_suggestion") and r.rowid not in picked_rowids:
                examples.append(("code_suggestion", r))
                break

        self.representative_examples = examples


# ---------------------------------------------------------------------------
# Step 1: Data Extraction
# ---------------------------------------------------------------------------


def extract_records(verbose: bool = False) -> list[ClusterRecord]:
    """Extract substantive pattern records from vec_reviews."""
    conn = get_vec_connection()

    # Build WHERE clause for theme exclusions
    theme_conditions = " AND ".join(
        f"theme NOT LIKE '%{t}%'" for t in _THEME_EXCLUDE
    )

    query = f"""
        SELECT rowid, embedding,
               {', '.join(_VEC_META_COLS)},
               {', '.join(_VEC_AUX_COLS)}
        FROM vec_reviews
        WHERE is_pattern = 1
          AND severity IN ('blocking', 'suggestion', 'nitpick')
          AND feedback_type NOT IN ('merge', 'praise')
          AND {theme_conditions}
    """

    if verbose:
        print(f"Executing extraction query...", file=sys.stderr)

    cursor = conn.execute(query)
    col_names = [desc[0] for desc in cursor.description]

    records = []
    for row in tqdm(cursor, desc="Loading records", file=sys.stderr):
        row_dict = dict(zip(col_names, row))
        rowid = row_dict.pop("rowid")
        emb_bytes = row_dict.pop("embedding")
        embedding = np.frombuffer(emb_bytes, dtype=np.float32).copy()

        meta = {k: row_dict[k] for k in row_dict}
        records.append(ClusterRecord(rowid=rowid, embedding=embedding, meta=meta))

    conn.close()

    if verbose:
        emb_bytes_total = len(records) * 768 * 4
        print(
            f"Loaded {len(records)} records, "
            f"~{emb_bytes_total / 1024 / 1024:.1f} MB embeddings",
            file=sys.stderr,
        )

    return records


# ---------------------------------------------------------------------------
# Step 2: Stratified Clustering
# ---------------------------------------------------------------------------


def stratified_cluster(
    records: list[ClusterRecord],
    min_cluster_size: int = 5,
    min_samples: int = 3,
    verbose: bool = False,
) -> list[Cluster]:
    """Partition records by (domain, language_context) and cluster each stratum."""
    # Group by stratum
    strata: dict[tuple, list[ClusterRecord]] = defaultdict(list)
    for r in records:
        key = (r.meta.get("domain", "unknown"), r.meta.get("language_context", "unknown"))
        strata[key].append(r)

    if verbose:
        print(f"Found {len(strata)} strata", file=sys.stderr)

    all_clusters = []
    cluster_id_counter = 0

    for stratum_key, stratum_records in tqdm(
        sorted(strata.items(), key=lambda x: -len(x[1])),
        desc="Clustering strata",
        file=sys.stderr,
    ):
        n = len(stratum_records)

        if n < min_cluster_size:
            # Too small to cluster -- treat as one group
            c = Cluster(
                cluster_id=cluster_id_counter,
                stratum=stratum_key,
                records=stratum_records,
            )
            c.compute_stats()
            all_clusters.append(c)
            cluster_id_counter += 1
            continue

        # Stack embeddings for HDBSCAN
        embeddings = np.stack([r.embedding for r in stratum_records])

        # Adjust min_cluster_size and min_samples for small strata
        effective_mcs = min(min_cluster_size, max(2, n // 4))
        effective_ms = min(min_samples, effective_mcs)

        clusterer = HDBSCAN(
            min_cluster_size=effective_mcs,
            min_samples=effective_ms,
            metric="cosine",
            cluster_selection_method="eom",
        )
        labels = clusterer.fit_predict(embeddings)

        # Group records by label
        label_groups: dict[int, list[ClusterRecord]] = defaultdict(list)
        for i, label in enumerate(labels):
            label_groups[label].append(stratum_records[i])

        if verbose:
            n_clusters = len([l for l in label_groups if l >= 0])
            n_noise = len(label_groups.get(-1, []))
            print(
                f"  {stratum_key[0]:20s}/{stratum_key[1]:15s}: "
                f"{n:5d} records -> {n_clusters} clusters, {n_noise} noise",
                file=sys.stderr,
            )

        for label, group_records in label_groups.items():
            if label == -1:
                # Noise points -- HDBSCAN couldn't assign these to any
                # coherent cluster, so discard them.
                continue
            c = Cluster(
                cluster_id=cluster_id_counter,
                stratum=stratum_key,
                records=group_records,
            )
            c.compute_stats()
            all_clusters.append(c)
            cluster_id_counter += 1

    if verbose:
        print(f"Total clusters before dedup: {len(all_clusters)}", file=sys.stderr)

    return all_clusters


# ---------------------------------------------------------------------------
# Step 4: Cross-Stratum Deduplication
# ---------------------------------------------------------------------------


def deduplicate_clusters(
    clusters: list[Cluster],
    threshold: float = 0.85,
    verbose: bool = False,
) -> list[Cluster]:
    """Merge clusters across strata if centroids are very similar and same domain."""
    if not clusters:
        return clusters

    # Build centroid matrix and domain list
    centroids = np.stack([c.centroid for c in clusters])
    domains = [c.stratum[0] for c in clusters]

    # Compute pairwise cosine similarity
    sim_matrix = cosine_similarity(centroids)

    # Find merge pairs (greedy union-find)
    parent = list(range(len(clusters)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            # Merge smaller into larger
            if clusters[ra].frequency < clusters[rb].frequency:
                parent[ra] = rb
            else:
                parent[rb] = ra

    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            if domains[i] == domains[j] and sim_matrix[i, j] > threshold:
                union(i, j)

    # Group by root
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(clusters)):
        groups[find(i)].append(i)

    merged = []
    merge_count = 0
    for root, members in groups.items():
        if len(members) == 1:
            merged.append(clusters[members[0]])
            continue

        merge_count += len(members) - 1

        # Merge all member clusters into one
        base = clusters[members[0]]
        combined_records = list(base.records)
        for m_idx in members[1:]:
            combined_records.extend(clusters[m_idx].records)

        # Use the stratum of the largest member
        largest_idx = max(members, key=lambda i: clusters[i].frequency)
        new_cluster = Cluster(
            cluster_id=base.cluster_id,
            stratum=clusters[largest_idx].stratum,
            records=combined_records,
        )
        new_cluster.compute_stats()
        merged.append(new_cluster)

    if verbose:
        print(
            f"Deduplication: {len(clusters)} -> {len(merged)} clusters "
            f"({merge_count} merges)",
            file=sys.stderr,
        )

    return merged


# ---------------------------------------------------------------------------
# Step 5: Checklist Item Generation
# ---------------------------------------------------------------------------


def generate_checklist_llm(
    clusters: list[Cluster],
    top_n: int,
    verbose: bool = False,
) -> list[Cluster]:
    """Use Claude CLI to generate checklist items for top clusters."""
    # Sort by importance, take top_n
    ranked = sorted(clusters, key=lambda c: c.importance, reverse=True)[:top_n]

    # Process in batches of 10
    batch_size = 10
    for batch_start in tqdm(
        range(0, len(ranked), batch_size),
        desc="Generating checklist items (LLM)",
        file=sys.stderr,
    ):
        batch = ranked[batch_start : batch_start + batch_size]
        _llm_batch(batch, verbose=verbose)

    return ranked


def _llm_batch(clusters: list[Cluster], verbose: bool = False):
    """Send a batch of clusters to Claude CLI for checklist generation."""
    cluster_descriptions = []
    for i, c in enumerate(clusters, 1):
        sev_str = ", ".join(f"{k}: {v}" for k, v in sorted(c.severity_counts.items()))
        comp_str = ", ".join(
            f"{k}({v})" for k, v in Counter(c.component_counts).most_common(3)
        )
        themes_str = "; ".join(c.top_themes[:3])
        keywords_str = ", ".join(c.top_keywords[:5])

        # Include 1-2 short example bodies
        example_bodies = []
        for _, rec in c.representative_examples[:2]:
            body = (rec.meta.get("body") or "")[:200].strip()
            if body:
                example_bodies.append(body)
        examples_str = "\n    ".join(f'"{b}"' for b in example_bodies)

        cluster_descriptions.append(
            f"Cluster {i}:\n"
            f"  Domain: {c.stratum[0]}, Language: {c.stratum[1]}\n"
            f"  Frequency: {c.frequency}, Severity: {sev_str}\n"
            f"  Components: {comp_str}\n"
            f"  Common themes: {themes_str}\n"
            f"  Keywords: {keywords_str}\n"
            f"  Examples:\n    {examples_str}\n"
        )

    prompt = (
        "You are analyzing clusters of code review feedback from the lead maintainer "
        "of MicroPython. For each cluster, generate a checklist item that PR authors "
        "should verify before submitting.\n\n"
        "For each cluster, provide:\n"
        "- CHECKLIST: An imperative sentence (e.g., 'Verify all macro arguments are "
        "parenthesized to prevent double evaluation')\n"
        "- EXPLANATION: 1-2 sentences explaining why this matters in MicroPython\n"
        "- APPLIES_TO: Scope description (e.g., 'C code in py/ and extmod/', "
        "'Python drivers', 'All documentation')\n\n"
        "Output one item per cluster, in order.\n\n"
        + "\n".join(cluster_descriptions)
    )

    try:
        cmd = [
            "claude",
            "-p",
            "--model", "haiku",
            "--output-format", "json",
            "--json-schema", json.dumps(_CHECKLIST_SCHEMA),
            "--no-session-persistence",
        ]

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            check=True,
            timeout=_LLM_TIMEOUT_SECONDS,
            env=env,
        )
        response = json.loads(result.stdout)
        items = response.get("structured_output", {}).get("items", [])

        for i, item in enumerate(items):
            if i < len(clusters):
                clusters[i].checklist_text = item.get("checklist", "")
                clusters[i].explanation_text = item.get("explanation", "")
                clusters[i].applies_to = item.get("applies_to", "")

    except subprocess.TimeoutExpired:
        print("  Claude CLI timed out, falling back to heuristic", file=sys.stderr)
        for c in clusters:
            _heuristic_checklist(c)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"  Claude CLI error: {e}, falling back to heuristic", file=sys.stderr)
        for c in clusters:
            _heuristic_checklist(c)


def generate_checklist_heuristic(
    clusters: list[Cluster],
    top_n: int,
    verbose: bool = False,
) -> list[Cluster]:
    """Generate checklist items using heuristic distillation (no LLM)."""
    ranked = sorted(clusters, key=lambda c: c.importance, reverse=True)[:top_n]
    for c in tqdm(ranked, desc="Generating checklist items (heuristic)", file=sys.stderr):
        _heuristic_checklist(c)
    return ranked


def _heuristic_checklist(cluster: Cluster):
    """Build a checklist description from the most common theme + keywords."""
    # Use most common theme as the base
    if cluster.top_themes:
        theme = cluster.top_themes[0]
    else:
        theme = f"{cluster.stratum[0]} review pattern"

    # Capitalize and ensure imperative form
    # Strip leading articles/verbs that make it non-imperative
    checklist = theme.strip()
    if checklist and checklist[0].islower():
        checklist = checklist[0].upper() + checklist[1:]

    # Prepend "Verify" if it doesn't start with a verb-like word
    _imperative_starts = (
        "Verify", "Check", "Ensure", "Use", "Add", "Remove", "Fix",
        "Avoid", "Include", "Update", "Replace", "Apply", "Follow",
        "Wrap", "Guard", "Handle", "Protect", "Document", "Test",
        "Consider", "Prefer", "Keep", "Set", "Move", "Split",
        "Rename", "Convert", "Implement", "Define", "Declare",
    )
    if not checklist.startswith(_imperative_starts):
        checklist = f"Check: {checklist}"

    cluster.checklist_text = checklist

    # Explanation from keywords and severity
    kws = ", ".join(cluster.top_keywords[:4]) if cluster.top_keywords else "general patterns"
    blocking = cluster.severity_counts.get("blocking", 0)
    if blocking > 0:
        cluster.explanation_text = (
            f"Frequently flagged in reviews ({cluster.frequency} occurrences, "
            f"{blocking} blocking). Key concerns: {kws}."
        )
    else:
        cluster.explanation_text = (
            f"Common review feedback ({cluster.frequency} occurrences). "
            f"Key concerns: {kws}."
        )

    # Applies-to from component and language
    components = [
        k for k, _ in Counter(cluster.component_counts).most_common(3)
    ]
    lang = cluster.stratum[1]
    lang_readable = {
        "c_code": "C files",
        "python_code": "Python files",
        "documentation": "documentation",
        "makefile": "Makefiles",
        "cmake": "CMake files",
        "shell_script": "shell scripts",
        "yaml": "YAML/CI configs",
    }.get(lang, lang)

    comp_readable = {
        "py_core": "py/",
        "extmod": "extmod/",
        "port_specific": "ports/*/",
        "drivers": "drivers/",
        "tools": "tools/",
        "tests": "tests/",
        "docs": "docs/",
        "build_system": "build system",
        "examples": "examples/",
    }
    comp_parts = [comp_readable.get(c, c) for c in components]
    if comp_parts:
        cluster.applies_to = f"{lang_readable} in {', '.join(comp_parts)}"
    else:
        cluster.applies_to = lang_readable


# ---------------------------------------------------------------------------
# Step 6: Output Assembly
# ---------------------------------------------------------------------------


def assemble_markdown(
    clusters: list[Cluster],
    verbose: bool = False,
) -> str:
    """Assemble the final markdown checklist."""
    lines = []
    lines.append("# MicroPython PR Author Checklist")
    lines.append("")
    lines.append(
        "Auto-generated from ~19.5K categorized review comments by the lead maintainer. "
        "Each item represents a cluster of related review feedback, ranked by importance."
    )
    lines.append("")

    # Group by domain
    by_domain: dict[str, list[Cluster]] = defaultdict(list)
    for c in clusters:
        by_domain[c.stratum[0]].append(c)

    # Order domains by total importance
    domain_order = sorted(
        by_domain.keys(),
        key=lambda d: sum(c.importance for c in by_domain[d]),
        reverse=True,
    )

    total_items = 0
    for domain in domain_order:
        domain_clusters = sorted(
            by_domain[domain], key=lambda c: c.importance, reverse=True
        )
        if not domain_clusters:
            continue

        domain_readable = {
            "code_style": "Code Style",
            "correctness": "Correctness",
            "api_design": "API Design",
            "architecture": "Architecture",
            "documentation": "Documentation",
            "testing": "Testing",
            "build_system": "Build System",
            "memory": "Memory",
            "portability": "Portability",
            "performance": "Performance",
            "error_handling": "Error Handling",
            "security": "Security",
        }.get(domain, domain.replace("_", " ").title())

        lines.append(f"## {domain_readable}")
        lines.append("")

        for c in domain_clusters:
            total_items += 1

            # Severity badge
            b = c.severity_counts.get("blocking", 0)
            s = c.severity_counts.get("suggestion", 0)
            n = c.severity_counts.get("nitpick", 0)
            sev_parts = []
            if b:
                sev_parts.append(f"{b} blocking")
            if s:
                sev_parts.append(f"{s} suggestion")
            if n:
                sev_parts.append(f"{n} nitpick")
            sev_str = ", ".join(sev_parts)

            lines.append(f"- [ ] **{c.checklist_text}**")
            lines.append(f"  - {c.explanation_text}")
            lines.append(f"  - *Applies to:* {c.applies_to}")
            lines.append(f"  - *Frequency:* {c.frequency} ({sev_str})")

            # Example quotes (up to 2, truncated)
            example_quotes = []
            for label, rec in c.representative_examples[:2]:
                body = (rec.meta.get("body") or "").strip()
                if not body:
                    continue
                # Truncate long bodies and collapse to single line
                body_oneline = " ".join(body.split())
                if len(body_oneline) > 200:
                    body_oneline = body_oneline[:197] + "..."
                example_quotes.append(body_oneline)

            if example_quotes:
                lines.append(f"  - Examples:")
                for q in example_quotes:
                    lines.append(f"    - > {q}")

            lines.append("")

    # Summary footer
    lines.append("---")
    lines.append("")
    lines.append(
        f"*{total_items} items across {len(domain_order)} domains. "
        f"Generated from {sum(c.frequency for c in clusters)} review comment clusters.*"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command()
@click.option("--top-n", default=80, help="Number of checklist items (default 80)")
@click.option(
    "--min-cluster-size", default=5, help="Minimum comments per cluster (default 5)"
)
@click.option("--skip-llm", is_flag=True, help="Skip Claude CLI, use heuristic distillation")
@click.option(
    "--output",
    type=click.Path(),
    default=None,
    help="Output file (default: docs/author_checklist.md)",
)
@click.option("--verbose", is_flag=True, help="Print cluster statistics")
def main(top_n, min_cluster_size, skip_llm, output, verbose):
    """Extract review patterns and build a PR author checklist."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if output is None:
        output = Path(__file__).parent.parent / "docs" / "author_checklist.md"
    else:
        output = Path(output)

    # Step 1: Extract records
    print("Step 1: Extracting pattern records...", file=sys.stderr)
    records = extract_records(verbose=verbose)
    if not records:
        print("No records found matching filter criteria.", file=sys.stderr)
        sys.exit(1)
    print(f"  {len(records)} records extracted", file=sys.stderr)

    # Step 2: Stratified clustering
    print("Step 2: Clustering by (domain, language_context) strata...", file=sys.stderr)
    clusters = stratified_cluster(
        records,
        min_cluster_size=min_cluster_size,
        min_samples=max(2, min_cluster_size - 2),
        verbose=verbose,
    )
    print(f"  {len(clusters)} clusters formed", file=sys.stderr)

    # Step 3: Stats already computed in compute_stats()

    # Step 4: Cross-stratum deduplication
    print("Step 4: Deduplicating across strata...", file=sys.stderr)
    clusters = deduplicate_clusters(clusters, threshold=0.85, verbose=verbose)
    print(f"  {len(clusters)} clusters after deduplication", file=sys.stderr)

    # Step 5: Checklist generation
    print("Step 5: Generating checklist items...", file=sys.stderr)
    if skip_llm:
        ranked = generate_checklist_heuristic(clusters, top_n=top_n, verbose=verbose)
    else:
        ranked = generate_checklist_llm(clusters, top_n=top_n, verbose=verbose)
    print(f"  {len(ranked)} items generated", file=sys.stderr)

    # Verbose cluster dump
    if verbose:
        print("\n=== Top 20 Clusters by Importance ===", file=sys.stderr)
        for i, c in enumerate(ranked[:20], 1):
            print(
                f"  {i:2d}. [{c.stratum[0]}/{c.stratum[1]}] "
                f"freq={c.frequency}, importance={c.importance:.1f}, "
                f"themes={c.top_themes[:2]}",
                file=sys.stderr,
            )

    # Step 6: Output
    print("Step 6: Assembling markdown...", file=sys.stderr)
    markdown = assemble_markdown(ranked, verbose=verbose)

    # Ensure output directory exists
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown)
    print(f"Wrote {len(ranked)} checklist items to {output}", file=sys.stderr)


if __name__ == "__main__":
    main()
