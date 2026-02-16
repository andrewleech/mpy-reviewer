#!/usr/bin/env python3
"""
Analyze review comment writing style.

Extracts patterns from review comments, issue comments, and review verdicts
to generate a style guide that captures voice, tone, and phrasing patterns.
"""

import sqlite3
import re
import sys
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional


@dataclass
class CommentStats:
    """Statistics for a single comment."""
    body: str
    comment_type: str  # 'review_comment', 'issue_comment', 'review'
    char_count: int
    word_count: int
    sentence_count: int
    has_code_ref: bool
    opening_phrase: Optional[str]
    patterns: List[str]


class StyleAnalyzer:
    """Analyzes review comment style from database."""

    # Regex patterns for analysis
    SENTENCE_PATTERN = re.compile(r'[.!?]+(?:\s|$)')
    WORD_PATTERN = re.compile(r'\b\w+\b')
    CODE_REF_PATTERN = re.compile(r'`[^`]+`|```[\s\S]*?```|\bline\s+\d+|@\w+')
    OPENING_PHRASE_PATTERN = re.compile(
        r'^([A-Z][^.!?]*?[.!?]|[A-Z][^.!?]*?(?=\n))'
    )

    # Common sentence starters in reviews
    IMPERATIVE_VERBS = {
        'use', 'add', 'remove', 'change', 'update', 'fix', 'move', 'rename',
        'split', 'merge', 'import', 'define', 'implement', 'check', 'handle',
        'consider', 'simplify', 'refactor', 'avoid', 'replace', 'return',
        'ensure', 'verify', 'test', 'document', 'clean', 'reorder'
    }

    QUESTION_WORDS = {'why', 'what', 'how', 'should', 'can', 'is', 'are', 'do'}

    SUGGESTION_STARTERS = {
        'might', 'could', 'perhaps', 'consider', 'should', 'would',
        'maybe', 'possibly', 'think', 'suggest', 'try'
    }

    def __init__(self, db_path: str):
        """Initialize analyzer with database path."""
        self.db_path = db_path
        self.comments: List[CommentStats] = []
        self.all_text = []

    def load_comments(self) -> int:
        """Load all comments from database."""
        print("Loading comments from database...", file=sys.stderr)
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Load review comments
            cursor.execute("SELECT body FROM review_comments WHERE body IS NOT NULL")
            for (body,) in cursor.fetchall():
                if body and body.strip():
                    self.comments.append(self._analyze_comment(body, 'review_comment'))
                    self.all_text.append(body)

            # Load issue comments
            cursor.execute("SELECT body FROM issue_comments WHERE body IS NOT NULL")
            for (body,) in cursor.fetchall():
                if body and body.strip():
                    self.comments.append(self._analyze_comment(body, 'issue_comment'))
                    self.all_text.append(body)

            # Load review verdicts
            cursor.execute("SELECT body FROM reviews WHERE body IS NOT NULL")
            for (body,) in cursor.fetchall():
                if body and body.strip():
                    self.comments.append(self._analyze_comment(body, 'review'))
                    self.all_text.append(body)

            conn.close()
            count = len(self.comments)
            print(f"Loaded {count} comments", file=sys.stderr)
            return count

        except sqlite3.DatabaseError as e:
            print(f"Database error: {e}", file=sys.stderr)
            return 0

    def _analyze_comment(self, body: str, comment_type: str) -> CommentStats:
        """Analyze a single comment."""
        char_count = len(body)
        words = self.WORD_PATTERN.findall(body.lower())
        word_count = len(words)
        sentences = self.SENTENCE_PATTERN.split(body)
        sentence_count = len([s for s in sentences if s.strip()])

        has_code_ref = bool(self.CODE_REF_PATTERN.search(body))
        opening = self._extract_opening_phrase(body)
        patterns = self._detect_patterns(body, words)

        return CommentStats(
            body=body,
            comment_type=comment_type,
            char_count=char_count,
            word_count=word_count,
            sentence_count=sentence_count,
            has_code_ref=has_code_ref,
            opening_phrase=opening,
            patterns=patterns
        )

    def _extract_opening_phrase(self, text: str) -> Optional[str]:
        """Extract first sentence or meaningful opening phrase."""
        match = self.OPENING_PHRASE_PATTERN.search(text)
        if match:
            phrase = match.group(1).strip()
            # Limit length for display
            return phrase[:80] if len(phrase) > 80 else phrase
        return None

    def _detect_patterns(self, body: str, words: List[str]) -> List[str]:
        """Detect sentence structure patterns."""
        patterns = []
        first_words = []

        # Get first word of each sentence
        sentences = self.SENTENCE_PATTERN.split(body)
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                first_word = sentence.split()[0].lower() if sentence.split() else None
                if first_word:
                    first_words.append(first_word)

        # Classify patterns
        if first_words:
            if any(w in self.IMPERATIVE_VERBS for w in first_words):
                patterns.append('imperative')
            if any(w in self.QUESTION_WORDS for w in first_words):
                patterns.append('question')
            if any(w in self.SUGGESTION_STARTERS for w in first_words):
                patterns.append('suggestion')

        # Punctuation patterns
        if '...' in body:
            patterns.append('ellipsis')
        if '**' in body or '__' in body:
            patterns.append('emphasis')
        if body.endswith('?'):
            patterns.append('ends_with_question')
        if body.endswith('!'):
            patterns.append('ends_with_exclamation')

        return patterns

    def analyze(self) -> Dict:
        """Run full analysis."""
        if not self.comments:
            print("Warning: No comments to analyze", file=sys.stderr)
            return self._empty_analysis()

        print(f"Analyzing {len(self.comments)} comments...", file=sys.stderr)

        stats = {
            'total_comments': len(self.comments),
            'by_type': self._analyze_by_type(),
            'length_stats': self._analyze_lengths(),
            'opening_phrases': self._analyze_opening_phrases(),
            'patterns': self._analyze_patterns(),
            'code_references': self._analyze_code_refs(),
            'common_words': self._analyze_common_words(),
            'punctuation': self._analyze_punctuation(),
            'sentence_structures': self._analyze_sentence_structures(),
        }

        return stats

    def _analyze_by_type(self) -> Dict:
        """Analyze comments by type."""
        by_type = defaultdict(list)
        for comment in self.comments:
            by_type[comment.comment_type].append(comment)

        result = {}
        for ctype, comments in by_type.items():
            result[ctype] = {
                'count': len(comments),
                'avg_chars': sum(c.char_count for c in comments) / len(comments),
                'avg_words': sum(c.word_count for c in comments) / len(comments),
                'avg_sentences': sum(c.sentence_count for c in comments) / len(comments),
            }
        return result

    def _analyze_lengths(self) -> Dict:
        """Analyze comment length distributions."""
        char_counts = [c.char_count for c in self.comments]
        word_counts = [c.word_count for c in self.comments]
        sentence_counts = [c.sentence_count for c in self.comments]

        def stats(values):
            if not values:
                return {}
            sorted_vals = sorted(values)
            return {
                'min': min(sorted_vals),
                'max': max(sorted_vals),
                'median': sorted_vals[len(sorted_vals) // 2],
                'avg': sum(sorted_vals) / len(sorted_vals),
            }

        return {
            'characters': stats(char_counts),
            'words': stats(word_counts),
            'sentences': stats(sentence_counts),
        }

    def _analyze_opening_phrases(self) -> Dict:
        """Analyze common opening phrases."""
        phrases = [c.opening_phrase for c in self.comments if c.opening_phrase]
        counter = Counter(phrases)
        return {
            'total_unique': len(set(phrases)),
            'most_common': counter.most_common(20)
        }

    def _analyze_patterns(self) -> Dict:
        """Analyze sentence structure patterns."""
        pattern_counter = Counter()
        for comment in self.comments:
            pattern_counter.update(comment.patterns)

        return dict(pattern_counter.most_common(15))

    def _analyze_code_refs(self) -> Dict:
        """Analyze code reference usage."""
        with_refs = sum(1 for c in self.comments if c.has_code_ref)
        return {
            'total_with_code_refs': with_refs,
            'percentage': (with_refs / len(self.comments) * 100) if self.comments else 0,
        }

    def _analyze_common_words(self) -> Dict:
        """Analyze most common words."""
        # Stop words to filter
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'be', 'to', 'of', 'in', 'for',
            'and', 'or', 'but', 'not', 'this', 'that', 'it', 'with',
            'on', 'at', 'by', 'from', 'as', 'i', 'you', 'we', 'they',
        }

        all_words = []
        for text in self.all_text:
            words = self.WORD_PATTERN.findall(text.lower())
            all_words.extend([w for w in words if w not in stop_words and len(w) > 2])

        counter = Counter(all_words)
        return dict(counter.most_common(30))

    def _analyze_punctuation(self) -> Dict:
        """Analyze punctuation patterns."""
        text_combined = ' '.join(self.all_text)
        return {
            'question_marks': text_combined.count('?'),
            'exclamation_marks': text_combined.count('!'),
            'ellipsis': text_combined.count('...'),
            'dashes': text_combined.count('-'),
            'parentheses': text_combined.count('('),
            'code_backticks': text_combined.count('`'),
        }

    def _analyze_sentence_structures(self) -> Dict:
        """Analyze sentence structure types."""
        imperative_count = sum(1 for c in self.comments if 'imperative' in c.patterns)
        question_count = sum(1 for c in self.comments if 'question' in c.patterns)
        suggestion_count = sum(1 for c in self.comments if 'suggestion' in c.patterns)

        total = len(self.comments)
        return {
            'imperative': {
                'count': imperative_count,
                'percentage': (imperative_count / total * 100) if total else 0
            },
            'question': {
                'count': question_count,
                'percentage': (question_count / total * 100) if total else 0
            },
            'suggestion': {
                'count': suggestion_count,
                'percentage': (suggestion_count / total * 100) if total else 0
            },
        }

    def _empty_analysis(self) -> Dict:
        """Return empty analysis structure."""
        return {
            'total_comments': 0,
            'by_type': {},
            'length_stats': {},
            'opening_phrases': {'total_unique': 0, 'most_common': []},
            'patterns': {},
            'code_references': {'total_with_code_refs': 0, 'percentage': 0},
            'common_words': {},
            'punctuation': {},
            'sentence_structures': {},
        }


def generate_style_guide(analysis: Dict, output_path: str) -> None:
    """Generate markdown style guide from analysis."""
    print(f"Generating style guide to {output_path}...", file=sys.stderr)

    output = ["# MicroPython Review Style Guide\n"]

    if analysis['total_comments'] == 0:
        output.append(
            "## Note\n\n"
            "The database is currently empty. This guide will be generated "
            "when comments are imported.\n"
        )
    else:
        output.append(_section_overview(analysis))
        output.append(_section_length(analysis))
        output.append(_section_structure(analysis))
        output.append(_section_openings(analysis))
        output.append(_section_patterns(analysis))
        output.append(_section_code_references(analysis))
        output.append(_section_common_words(analysis))
        output.append(_section_recommendations())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write('\n'.join(output))

    print(f"Style guide written to {output_path}", file=sys.stderr)


def _section_overview(analysis: Dict) -> str:
    """Generate overview section."""
    lines = ["## Overview\n"]
    lines.append(f"Total comments analyzed: **{analysis['total_comments']}**\n")

    by_type = analysis['by_type']
    if by_type:
        lines.append("\n### Comments by Type\n")
        for ctype, stats in by_type.items():
            lines.append(f"\n**{ctype}**: {stats['count']} comments")
            lines.append(f"- Average: {stats['avg_words']:.1f} words, "
                        f"{stats['avg_chars']:.0f} chars")
            lines.append(f"- Average sentences per comment: {stats['avg_sentences']:.1f}")

    return '\n'.join(lines)


def _section_length(analysis: Dict) -> str:
    """Generate length analysis section."""
    lines = ["\n## Length Distribution\n"]
    lengths = analysis['length_stats']

    if 'words' in lengths and lengths['words']:
        words = lengths['words']
        lines.append("### By Word Count\n")
        lines.append(f"- Minimum: {words.get('min', 'N/A')} words")
        lines.append(f"- Maximum: {words.get('max', 'N/A')} words")
        lines.append(f"- Median: {words.get('median', 'N/A'):.0f} words")
        lines.append(f"- Average: {words.get('avg', 'N/A'):.1f} words")

    if 'characters' in lengths and lengths['characters']:
        chars = lengths['characters']
        lines.append("\n### By Character Count\n")
        lines.append(f"- Minimum: {chars.get('min', 'N/A')} chars")
        lines.append(f"- Maximum: {chars.get('max', 'N/A')} chars")
        lines.append(f"- Median: {chars.get('median', 'N/A'):.0f} chars")
        lines.append(f"- Average: {chars.get('avg', 'N/A'):.1f} chars")

    if 'sentences' in lengths and lengths['sentences']:
        sentences = lengths['sentences']
        lines.append("\n### By Sentence Count\n")
        lines.append(f"- Minimum: {sentences.get('min', 'N/A')} sentences")
        lines.append(f"- Maximum: {sentences.get('max', 'N/A')} sentences")
        lines.append(f"- Median: {sentences.get('median', 'N/A'):.0f} sentences")
        lines.append(f"- Average: {sentences.get('avg', 'N/A'):.1f} sentences")

    lines.append("\n### Interpretation\n")
    lines.append("Comments tend to be **direct and concise**. Avoid lengthy explanations; "
                "get to the point in 1-3 sentences.")

    return '\n'.join(lines)


def _section_structure(analysis: Dict) -> str:
    """Generate sentence structure section."""
    lines = ["\n## Sentence Structure Patterns\n"]

    structures = analysis['sentence_structures']
    if structures:
        lines.append("### Distribution\n")
        for stype, data in structures.items():
            pct = data.get('percentage', 0)
            count = data.get('count', 0)
            lines.append(f"- **{stype.capitalize()}**: {count} comments ({pct:.1f}%)")

        # Determine dominant style
        sorted_structures = sorted(
            structures.items(),
            key=lambda x: x[1].get('percentage', 0),
            reverse=True
        )
        if sorted_structures:
            dominant = sorted_structures[0][0]
            lines.append(f"\nDominant style: **{dominant} sentences**")

    return '\n'.join(lines)


def _section_openings(analysis: Dict) -> str:
    """Generate opening phrases section."""
    lines = ["\n## Common Opening Phrases\n"]
    lines.append("Effective ways to start review comments:\n")

    openings = analysis['opening_phrases']
    if openings['most_common']:
        for phrase, count in openings['most_common'][:10]:
            lines.append(f"- {phrase}")
    else:
        lines.append("(No opening phrases available in sample)")

    return '\n'.join(lines)


def _section_patterns(analysis: Dict) -> str:
    """Generate patterns section."""
    lines = ["\n## Common Patterns\n"]

    patterns = analysis['patterns']
    if patterns:
        lines.append("### Sentence Features\n")
        for pattern, count in patterns.items():
            lines.append(f"- **{pattern}**: {count} comments")
    else:
        lines.append("(No patterns detected)")

    return '\n'.join(lines)


def _section_code_references(analysis: Dict) -> str:
    """Generate code reference section."""
    lines = ["\n## Code References\n"]

    refs = analysis['code_references']
    pct = refs['percentage']
    lines.append(f"{pct:.1f}% of comments include code references (backticks, line numbers, etc)\n")

    lines.append("### Best Practices\n")
    lines.append("- Use backticks for identifiers: `variable_name`, `function()`")
    lines.append("- Reference line numbers when discussing specific code")
    lines.append("- Use diffs or code blocks for larger examples")
    lines.append("- Mention specific files when relevant to the change")

    return '\n'.join(lines)


def _section_common_words(analysis: Dict) -> str:
    """Generate common words section."""
    lines = ["\n## Frequently Used Words\n"]
    lines.append("(Excluding common stop words)\n")

    words = analysis['common_words']
    if words:
        lines.append("### Top 30 Words\n")
        for i, (word, count) in enumerate(list(words.items())[:30], 1):
            lines.append(f"{i}. **{word}** ({count})")
    else:
        lines.append("(No word frequency data available)")

    return '\n'.join(lines)


def _section_recommendations() -> str:
    """Generate recommendations section."""
    return """
## Recommendations for Review Comments

### Voice & Tone
- **Direct**: Get straight to the issue. No filler or pleasantries.
- **Technical**: Assume reader understands the codebase. Use precise terms.
- **Constructive**: Point out problems clearly, but frame suggestions helpfully.
- **Terse**: Use minimal words. Longer does not mean better.

### Writing Guidelines

**DO:**
- Start with the problem or action needed
- Use active voice and imperative when appropriate
- Reference specific code locations (line numbers, identifiers)
- Include code examples when clarifying
- Ask questions to prompt thinking when appropriate
- Use emphasis (`**bold**`, `` `code` ``) sparingly

**DON'T:**
- Add filler words ("I think", "maybe", "probably")
- Use softening language unless necessary
- Write multiple sentences when one will do
- Quote large blocks of code
- Use vague pronouns without antecedents
- Over-explain obvious points

### Comment Types

**For bugs/issues:**
```
[Verb]: [Problem statement].
```
Example: `Fix: This leaks memory on every iteration.`

**For improvements:**
```
[Suggestion]: [Change] to [benefit].
```
Example: `Consider: Use a static buffer here to reduce allocations.`

**For questions:**
```
Why [question]? [Context if needed].
```
Example: `Why malloc instead of the arena allocator?`

**For approval/final comments:**
Short acknowledgment or specific praise for clever solutions.

### Structure
- Lead with the most important point
- Group related feedback together
- One clear issue per comment when possible
- Use lists for multiple items
"""


def main() -> int:
    """Main entry point."""
    script_dir = Path(__file__).parent
    db_path = script_dir.parent / 'data' / 'reviews.db'
    output_path = script_dir.parent / 'output' / 'style_guide.md'

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}", file=sys.stderr)
        return 1

    analyzer = StyleAnalyzer(str(db_path))
    count = analyzer.load_comments()

    if count > 0:
        print(f"Successfully loaded {count} comments", file=sys.stderr)
    else:
        print("Note: Database is empty or contains no comments", file=sys.stderr)

    analysis = analyzer.analyze()
    generate_style_guide(analysis, str(output_path))

    return 0


if __name__ == '__main__':
    sys.exit(main())
