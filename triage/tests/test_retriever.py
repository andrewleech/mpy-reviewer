"""Tests for issue retriever."""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import numpy as np

from triage.retriever import (
    IssueRetriever, _title_word_overlap, _sanitize_fts_query,
)


class TestTitleWordOverlap:
    def test_identical_titles(self):
        assert _title_word_overlap("UART bug on ESP32", "UART bug on ESP32") > 0.5

    def test_similar_titles(self):
        overlap = _title_word_overlap("UART not working", "UART fails to work")
        assert overlap > 0

    def test_no_overlap(self):
        assert _title_word_overlap("UART bug", "I2C enhancement") == 0.0

    def test_empty_title(self):
        assert _title_word_overlap("", "something") == 0.0
        assert _title_word_overlap("something", "") == 0.0

    def test_stopwords_ignored(self):
        # "the", "a", "is", "in" should be ignored
        overlap = _title_word_overlap("the UART is broken", "a UART in trouble")
        # Only "UART" overlaps
        assert overlap > 0


class TestSanitizeFtsQuery:
    def test_simple_query(self):
        result = _sanitize_fts_query("UART ESP32")
        assert '"UART"' in result
        assert '"ESP32"' in result

    def test_special_chars_removed(self):
        result = _sanitize_fts_query('test "quoted" (paren)')
        assert "(" not in result.replace('"', '')
        assert ")" not in result.replace('"', '')

    def test_empty_query(self):
        result = _sanitize_fts_query("")
        assert result == '""'


class TestIssueRetrieverClosingRefs:
    def test_check_closing_refs_with_data(self, populated_db):
        """Test closing refs query with inserted data."""
        populated_db.execute(
            "INSERT INTO issue_closing_refs (issue_number, issue_repo, pr_number, pr_repo, pr_merged) "
            "VALUES (100, 'micropython/micropython', 500, 'micropython/micropython', 1)"
        )
        populated_db.commit()

        retriever = IssueRetriever()
        retriever._conn = populated_db
        refs = retriever.check_closing_refs(100, "micropython/micropython")
        assert len(refs) == 1
        assert refs[0]["pr_number"] == 500
        assert refs[0]["pr_merged"] is True

    def test_check_closing_refs_empty(self, populated_db):
        retriever = IssueRetriever()
        retriever._conn = populated_db
        refs = retriever.check_closing_refs(999, "micropython/micropython")
        assert refs == []


class TestIssueRetrieverGetIssue:
    def test_get_existing_issue(self, populated_db):
        retriever = IssueRetriever()
        retriever._conn = populated_db
        issue = retriever.get_issue(100, "micropython/micropython")
        assert issue is not None
        assert issue["title"] == "UART not working on ESP32"

    def test_get_nonexistent_issue(self, populated_db):
        retriever = IssueRetriever()
        retriever._conn = populated_db
        issue = retriever.get_issue(999, "micropython/micropython")
        assert issue is None
