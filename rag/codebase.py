"""Codebase context retrieval for MicroPython source code.

Uses the codanna CLI binary (Rust) for semantic code search when available,
with regex-based fallback for environments without codanna or when codanna
returns no results.
"""

from typing import List, Dict, Any, Optional, Set
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import get_config

logger = logging.getLogger(__name__)


class CodebaseRetriever:
    """Retrieve relevant code context from MicroPython codebase."""

    def __init__(self, repo_path: Optional[Path] = None):
        config = get_config()
        self.repo_path = repo_path or config.micropython_repo_path
        self._codanna_available = False
        self._codanna_binary: Optional[str] = None
        self._codanna_warned = False
        self._file_cache: Dict[str, str] = {}

        if self.repo_path is None:
            logger.warning(
                "No MicroPython repo found (not inside a checkout and none configured). "
                "Codebase context will be empty."
            )
            return

        self._detect_codanna()
        if self._codanna_available:
            self._ensure_index()

    # ------------------------------------------------------------------ #
    # codanna detection and index management
    # ------------------------------------------------------------------ #

    def _detect_codanna(self) -> None:
        """Find the codanna binary. Sets _codanna_available and _codanna_binary."""
        binary = shutil.which("codanna")
        if binary is None:
            cargo_path = Path.home() / ".cargo" / "bin" / "codanna"
            if cargo_path.is_file() and os.access(cargo_path, os.X_OK):
                binary = str(cargo_path)

        if binary is None:
            self._warn_codanna_missing()
            return

        self._codanna_binary = binary
        self._codanna_available = True
        logger.info("codanna found at %s", binary)

    def _warn_codanna_missing(self) -> None:
        """Log a one-shot warning with install guidance."""
        if self._codanna_warned:
            return
        self._codanna_warned = True

        if shutil.which("cargo"):
            msg = (
                "codanna not found. Install with: cargo install codanna --all-features\n"
                "Falling back to regex-based symbol search."
            )
        else:
            msg = (
                "codanna not found (Rust/cargo not on PATH).\n"
                "Install Rust: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh\n"
                "Then: cargo install codanna --all-features\n"
                "Or download a binary from https://github.com/bartolli/codanna/releases\n"
                "Falling back to regex-based symbol search."
            )
        logger.warning(msg)

    def _ensure_index(self) -> None:
        """Ensure the codanna index exists for repo_path; build if missing."""
        codanna_dir = self.repo_path / ".codanna"
        if codanna_dir.is_dir():
            return

        logger.info("codanna index not found at %s — building...", codanna_dir)

        # init
        ok = self._run_codanna_raw(["init"], timeout=30)
        if not ok:
            logger.warning("codanna init failed; disabling codanna")
            self._codanna_available = False
            return

        # index the whole repo (may take a few minutes for large repos)
        ok = self._run_codanna_raw(["index", "--no-progress", "."], timeout=300)
        if not ok:
            logger.warning("codanna index build failed; disabling codanna")
            self._codanna_available = False
            return

        # Add .codanna/ to .git/info/exclude so it doesn't pollute git status
        git_exclude = self.repo_path / ".git" / "info" / "exclude"
        if git_exclude.is_file():
            try:
                content = git_exclude.read_text()
                if not re.search(r'^\s*\.codanna/?$', content, re.MULTILINE):
                    suffix = "" if content.endswith("\n") else "\n"
                    with open(git_exclude, "a") as f:
                        f.write(f"{suffix}.codanna/\n")
            except OSError:
                pass

        logger.info("codanna index built for %s", self.repo_path)

    def _run_codanna_raw(self, args: list, timeout: int = 30) -> bool:
        """Run an arbitrary codanna command. Returns True on success."""
        try:
            result = subprocess.run(
                [self._codanna_binary, *args],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                logger.debug("codanna %s failed: %s", args[0], result.stderr.strip())
                return False
            return True
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("codanna %s error: %s", args[0], e)
            return False

    def _run_codanna(self, *mcp_args: str) -> Optional[list]:
        """Run ``codanna mcp <args> --json`` and return the ``data`` field.

        Returns None on error, timeout, or not_found status.
        """
        if not self._codanna_available:
            return None

        cmd = [self._codanna_binary, "mcp", *mcp_args, "--json"]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.debug("codanna mcp %s error: %s", mcp_args[0], e)
            return None

        if result.returncode != 0:
            logger.debug(
                "codanna mcp %s exited %d: %s",
                mcp_args[0], result.returncode, result.stderr.strip(),
            )

        # Parse JSON from stdout (skip any non-JSON warning lines on stderr)
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            logger.debug("codanna mcp %s: invalid JSON output", mcp_args[0])
            return None

        if payload.get("status") != "success":
            return None

        return payload.get("data")

    # ------------------------------------------------------------------ #
    # Identifier / path extraction (unchanged)
    # ------------------------------------------------------------------ #

    def extract_identifiers(self, code_text: str) -> Set[str]:
        """Extract potential identifiers (function names, macros, types) from code."""
        identifiers = set()

        c_patterns = [
            r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(',  # function calls
            r'\b(MP_[A-Z_]+)\b',  # MicroPython macros
            r'\b(mp_[a-z_]+)\b',  # MicroPython functions
            r'#include\s*[<"]([^>"]+)[>"]',  # includes
        ]

        for pattern in c_patterns:
            matches = re.findall(pattern, code_text)
            identifiers.update(matches)

        return identifiers

    def extract_file_paths(self, diff_text: str) -> Set[str]:
        """Extract file paths from diff."""
        paths = set()

        patterns = [
            r'^(?:---|\+\+\+)\s+[ab]/(.+?)(?:\s|$)',
            r'^diff\s+--git\s+a/(.+?)\s+b/',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, diff_text, re.MULTILINE)
            paths.update(matches)

        return paths

    def get_file_content(self, file_path: str, start_line: Optional[int] = None,
                        end_line: Optional[int] = None) -> Optional[str]:
        """Get content of a file from the repository."""
        if self.repo_path is None:
            return None

        full_path = (self.repo_path / file_path).resolve()

        try:
            if not full_path.is_relative_to(self.repo_path.resolve()):
                logger.warning("Path traversal blocked: %s", file_path)
                return None
            if not full_path.exists():
                logger.debug(f"File not found: {full_path}")
                return None

            content = full_path.read_text(encoding='utf-8', errors='ignore')

            if start_line is not None and end_line is not None:
                lines = content.split('\n')
                start_idx = max(0, start_line - 1)
                end_idx = min(len(lines), end_line)
                content = '\n'.join(lines[start_idx:end_idx])

            return content
        except Exception as e:
            logger.warning(f"Error reading file {file_path}: {e}")
            return None

    # ------------------------------------------------------------------ #
    # Symbol lookup
    # ------------------------------------------------------------------ #

    def find_symbol_definition(self, symbol_name: str) -> Optional[Dict[str, Any]]:
        """Find definition of a symbol in the codebase.

        Tries codanna first, falls through to regex if codanna returns nothing
        (handles symbols codanna's parser misses, e.g. some C macros).
        """
        if not symbol_name:
            return None

        # Try codanna
        data = self._run_codanna("find_symbol", symbol_name)
        if data and isinstance(data, list) and len(data) > 0:
            entry = data[0]
            sym = entry.get("symbol", {})
            file_path = entry.get("file_path") or sym.get("file_path", "")
            # Normalize leading ./ from codanna paths
            if file_path.startswith("./"):
                file_path = file_path[2:]
            start_line = max(1, sym.get("range", {}).get("start_line", 1))

            # Get surrounding context from the file
            context = ""
            content = self.get_file_content(file_path, start_line - 3, start_line + 4)
            if content:
                lines = content.split('\n')
                base = max(1, start_line - 3)
                context = '\n'.join(
                    f"{base + i:4d}: {line}" for i, line in enumerate(lines)
                )

            return {
                "symbol": symbol_name,
                "type": sym.get("kind", "unknown").lower(),
                "file": file_path,
                "line": start_line,
                "context": context,
            }

        # Fall through to regex
        return self._find_symbol_regex(symbol_name)

    def _find_symbol_regex(self, symbol_name: str) -> Optional[Dict[str, Any]]:
        """Regex-based symbol search (fallback)."""
        if self.repo_path is None:
            return None

        patterns = {
            "function": rf'^[a-zA-Z_][a-zA-Z0-9_*\s]*{re.escape(symbol_name)}\s*\(',
            "macro": rf'^#define\s+{re.escape(symbol_name)}\b',
            "typedef": rf'^typedef\s+.*{re.escape(symbol_name)}\b',
            "struct": rf'^typedef\s+struct\s*{{?.*?}}\s*{re.escape(symbol_name)};',
        }

        search_dirs = [
            self.repo_path / "py",
            self.repo_path / "extmod",
            self.repo_path / "shared",
            self.repo_path / "ports",
        ]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for file_path in search_dir.rglob("*.[ch]"):
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    lines = content.split('\n')

                    for line_num, line in enumerate(lines, 1):
                        for symbol_type, pattern in patterns.items():
                            if re.search(pattern, line):
                                relative_path = file_path.relative_to(self.repo_path)
                                start = max(0, line_num - 4)
                                end = min(len(lines), line_num + 3)
                                context = '\n'.join(
                                    f"{i:4d}: {lines[i-1]}"
                                    for i in range(start, end + 1)
                                )

                                return {
                                    "symbol": symbol_name,
                                    "type": symbol_type,
                                    "file": str(relative_path),
                                    "line": line_num,
                                    "context": context,
                                }
                except Exception as e:
                    logger.debug(f"Error searching {file_path}: {e}")

        return None

    # ------------------------------------------------------------------ #
    # Related definitions
    # ------------------------------------------------------------------ #

    def find_related_definitions(self, diff_text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Find related code definitions for a diff."""
        definitions = []

        identifiers = self.extract_identifiers(diff_text)
        logger.debug(f"Extracted {len(identifiers)} identifiers from diff")

        # codanna lookups are fast (~10ms each), so search more identifiers
        search_cap = 20 if self._codanna_available else 10

        for identifier in sorted(identifiers)[:search_cap]:
            defn = self.find_symbol_definition(identifier)
            if defn:
                definitions.append(defn)
                if len(definitions) >= limit:
                    break

        return definitions

    # ------------------------------------------------------------------ #
    # Similar patterns
    # ------------------------------------------------------------------ #

    def get_similar_code_patterns(self, code_snippet: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Find similar code patterns elsewhere in the codebase."""
        # Try codanna semantic search
        data = self._run_codanna(
            "semantic_search_docs",
            f"query:{code_snippet[:500]}",
            f"limit:{limit}",
        )
        if data and isinstance(data, list) and len(data) > 0:
            patterns = []
            for entry in data[:limit]:
                sym = entry.get("symbol", {})
                file_path = sym.get("file_path", "")
                if file_path.startswith("./"):
                    file_path = file_path[2:]
                # Estimate file size from line range
                rng = sym.get("range", {})
                size = (rng.get("end_line", 0) - rng.get("start_line", 0) + 1) * 40
                patterns.append({
                    "file": file_path,
                    "match_count": 1,
                    "keywords_matched": [sym.get("name", "")],
                    "size": size,
                })
            return patterns

        # Fall through to regex
        return self._similar_patterns_regex(code_snippet, limit)

    def _similar_patterns_regex(self, code_snippet: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Regex/keyword-based similar pattern search (fallback)."""
        if self.repo_path is None:
            return []

        patterns = []

        keywords = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]{2,})\b', code_snippet)
        if not keywords:
            return patterns

        keyword_set = set(keywords[:5])

        search_dirs = [self.repo_path / d for d in ["py", "extmod", "shared"]]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for file_path in search_dir.rglob("*.[ch]"):
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')

                    match_count = sum(1 for kw in keyword_set if kw in content)

                    if match_count >= len(keyword_set) - 1:
                        relative_path = file_path.relative_to(self.repo_path)
                        patterns.append({
                            "file": str(relative_path),
                            "match_count": match_count,
                            "keywords_matched": list(keyword_set),
                            "size": len(content),
                        })

                        if len(patterns) >= limit:
                            return sorted(patterns, key=lambda x: -x["match_count"])
                except Exception as e:
                    logger.debug(f"Error analyzing {file_path}: {e}")

        return patterns

    # ------------------------------------------------------------------ #
    # Composite context
    # ------------------------------------------------------------------ #

    def get_context_for_diff(self, diff_text: str, top_k: int = 5) -> Dict[str, Any]:
        """Get context for a code diff."""
        context = {
            "files_changed": list(self.extract_file_paths(diff_text)),
            "related_definitions": self.find_related_definitions(diff_text, limit=top_k),
            "similar_patterns": self.get_similar_code_patterns(diff_text, limit=top_k),
            "identifiers_found": list(self.extract_identifiers(diff_text))[:10],
        }

        return context


# Global codebase retriever instance
_codebase_retriever: Optional[CodebaseRetriever] = None


def get_codebase_retriever() -> CodebaseRetriever:
    """Get the global codebase retriever instance."""
    global _codebase_retriever
    if _codebase_retriever is None:
        _codebase_retriever = CodebaseRetriever()
    return _codebase_retriever


def extract_diff_file_paths(diff_text: str) -> List[str]:
    """Extract file paths from a unified diff.

    Module-level utility so callers don't need a CodebaseRetriever instance.
    """
    paths: Set[str] = set()
    for pattern in [
        r"^diff\s+--git\s+a/(.+?)\s+b/",
        r"^(?:---|\+\+\+)\s+[ab]/(.+?)(?:\s|$)",
    ]:
        paths.update(re.findall(pattern, diff_text, re.MULTILINE))
    return sorted(paths)


def get_code_context(diff_text: str, top_k: int = 5) -> Dict[str, Any]:
    """Convenience function to get code context for a diff."""
    retriever = get_codebase_retriever()
    return retriever.get_context_for_diff(diff_text, top_k=top_k)
