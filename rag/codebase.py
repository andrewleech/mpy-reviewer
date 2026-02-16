"""Codebase context retrieval using Codanna for MicroPython source code."""

from typing import List, Dict, Any, Optional, Set
import logging
import re
from pathlib import Path

from .config import get_config

logger = logging.getLogger(__name__)


class CodebaseRetriever:
    """Retrieve relevant code context from MicroPython codebase using Codanna."""

    def __init__(self, repo_path: Optional[Path] = None):
        """Initialize the codebase retriever.

        Args:
            repo_path: Path to MicroPython repository (default from config)
        """
        config = get_config()
        self.repo_path = repo_path or config.micropython_repo_path
        self._codanna_available = self._check_codanna()
        self._file_cache: Dict[str, str] = {}

    def _check_codanna(self) -> bool:
        """Check if codanna is available and index exists.

        Raises:
            RuntimeError: If codanna is not available (hard requirement)
        """
        try:
            # Try to import codanna
            import codanna
            logger.info("Codanna is available")
            return True
        except ImportError:
            error_msg = (
                "\n"
                "╔══════════════════════════════════════════════════════════════════════╗\n"
                "║ CRITICAL: codanna is required for codebase context retrieval         ║\n"
                "╠══════════════════════════════════════════════════════════════════════╣\n"
                "║                                                                      ║\n"
                "║ This tool requires codanna for semantic code search and analysis.   ║\n"
                "║                                                                      ║\n"
                "║ Installation:                                                        ║\n"
                "║   1. Install Rust if not installed:                                 ║\n"
                "║      curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh ║\n"
                "║                                                                      ║\n"
                "║   2. Install codanna:                                                ║\n"
                "║      cargo install codanna --all-features                            ║\n"
                "║                                                                      ║\n"
                "║   3. Ensure ~/.cargo/bin is in PATH                                  ║\n"
                "║                                                                      ║\n"
                "║ For automatic installation via Claude Code SessionStart hook,       ║\n"
                "║ see: docs/CLAUDE_SETUP.md                                            ║\n"
                "║                                                                      ║\n"
                "╚══════════════════════════════════════════════════════════════════════╝\n"
            )
            logger.error(error_msg)
            raise RuntimeError(
                "codanna is required but not installed. "
                "Install with: cargo install codanna --all-features"
            )

    def extract_identifiers(self, code_text: str) -> Set[str]:
        """Extract potential identifiers (function names, macros, types) from code.

        Args:
            code_text: Code text to analyze

        Returns:
            Set of candidate identifiers
        """
        identifiers = set()

        # C function/macro patterns
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
        """Extract file paths from diff.

        Args:
            diff_text: Unified diff text

        Returns:
            Set of file paths modified
        """
        paths = set()

        # Pattern: --- a/path/to/file or +++ b/path/to/file
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
        """Get content of a file from the repository.

        Args:
            file_path: Path to file (relative to repo)
            start_line: Optional start line (1-indexed)
            end_line: Optional end line (1-indexed)

        Returns:
            File content or lines, or None if not found
        """
        full_path = self.repo_path / file_path

        try:
            if not full_path.exists():
                logger.debug(f"File not found: {full_path}")
                return None

            content = full_path.read_text(encoding='utf-8', errors='ignore')

            if start_line is not None and end_line is not None:
                lines = content.split('\n')
                # Convert to 0-indexed
                start_idx = max(0, start_line - 1)
                end_idx = min(len(lines), end_line)
                content = '\n'.join(lines[start_idx:end_idx])

            return content
        except Exception as e:
            logger.warning(f"Error reading file {file_path}: {e}")
            return None

    def find_symbol_definition(self, symbol_name: str) -> Optional[Dict[str, Any]]:
        """Find definition of a symbol in the codebase.

        This is a simplified version that searches for patterns.
        With Codanna integration, this would be much more sophisticated.

        Args:
            symbol_name: Symbol to search for

        Returns:
            Dictionary with symbol info (path, line, context) or None
        """
        if not symbol_name:
            return None

        # Patterns for different symbol types
        patterns = {
            "function": rf'^[a-zA-Z_][a-zA-Z0-9_*\s]*{re.escape(symbol_name)}\s*\(',
            "macro": rf'^#define\s+{re.escape(symbol_name)}\b',
            "typedef": rf'^typedef\s+.*{re.escape(symbol_name)}\b',
            "struct": rf'^typedef\s+struct\s*{{?.*?}}\s*{re.escape(symbol_name)};',
        }

        # Search in key directories
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
                                # Found the symbol
                                relative_path = file_path.relative_to(self.repo_path)
                                # Get surrounding context (±3 lines)
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

    def find_related_definitions(self, diff_text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Find related code definitions for a diff.

        Args:
            diff_text: Code diff to analyze
            limit: Maximum number of definitions to return

        Returns:
            List of related definitions with context
        """
        definitions = []

        # Extract identifiers from diff
        identifiers = self.extract_identifiers(diff_text)
        logger.debug(f"Extracted {len(identifiers)} identifiers from diff")

        # Find definitions for key identifiers
        for identifier in sorted(identifiers)[:10]:  # Limit search
            defn = self.find_symbol_definition(identifier)
            if defn:
                definitions.append(defn)
                if len(definitions) >= limit:
                    break

        return definitions

    def get_similar_code_patterns(self, code_snippet: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Find similar code patterns elsewhere in the codebase.

        Args:
            code_snippet: Code snippet to find patterns for
            limit: Maximum patterns to return

        Returns:
            List of similar code occurrences
        """
        patterns = []

        # Extract keywords and patterns from snippet
        keywords = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]{2,})\b', code_snippet)
        if not keywords:
            return patterns

        # Search for files containing multiple keywords
        keyword_set = set(keywords[:5])  # Use first 5 keywords

        search_dirs = [self.repo_path / d for d in ["py", "extmod", "shared"]]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for file_path in search_dir.rglob("*.[ch]"):
                try:
                    content = file_path.read_text(encoding='utf-8', errors='ignore')

                    # Count keyword matches
                    match_count = sum(1 for kw in keyword_set if kw in content)

                    if match_count >= len(keyword_set) - 1:  # Most keywords present
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

    def get_context_for_diff(self, diff_text: str, top_k: int = 5) -> Dict[str, Any]:
        """Get comprehensive context for a code diff.

        Args:
            diff_text: Unified diff text
            top_k: Number of results to return

        Returns:
            Dictionary with retrieved context
        """
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
    """Convenience function to get code context for a diff.

    Args:
        diff_text: Code diff
        top_k: Number of definitions to retrieve

    Returns:
        Code context
    """
    retriever = get_codebase_retriever()
    return retriever.get_context_for_diff(diff_text, top_k=top_k)
