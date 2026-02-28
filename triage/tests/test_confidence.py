"""Tests for triage confidence scoring."""

import pytest
from unittest.mock import patch
from triage.confidence import (
    TriageAction, compute_duplicate_confidence, apply_confidence_policy,
)
from rag.config import TriageConfig


@pytest.fixture
def default_config():
    return TriageConfig()


class TestComputeDuplicateConfidence:
    @patch("triage.confidence.get_triage_config")
    def test_merged_closing_ref_gives_high_confidence(self, mock_config):
        mock_config.return_value = TriageConfig()
        confidence = compute_duplicate_confidence(
            similarity_score=0.5,
            has_merged_closing_ref=True,
        )
        assert confidence == 0.95

    @patch("triage.confidence.get_triage_config")
    def test_high_similarity_gives_high_confidence(self, mock_config):
        mock_config.return_value = TriageConfig()
        confidence = compute_duplicate_confidence(
            similarity_score=0.95,
            has_merged_closing_ref=False,
        )
        assert confidence >= 0.85

    @patch("triage.confidence.get_triage_config")
    def test_medium_similarity_gives_medium_confidence(self, mock_config):
        mock_config.return_value = TriageConfig()
        confidence = compute_duplicate_confidence(
            similarity_score=0.75,
            has_merged_closing_ref=False,
        )
        assert 0.6 <= confidence < 0.85

    @patch("triage.confidence.get_triage_config")
    def test_low_similarity_gives_low_confidence(self, mock_config):
        mock_config.return_value = TriageConfig()
        confidence = compute_duplicate_confidence(
            similarity_score=0.3,
            has_merged_closing_ref=False,
        )
        assert confidence < 0.6

    @patch("triage.confidence.get_triage_config")
    def test_title_overlap_boosts_confidence(self, mock_config):
        mock_config.return_value = TriageConfig()
        base = compute_duplicate_confidence(0.8, False, title_overlap=0.0)
        boosted = compute_duplicate_confidence(0.8, False, title_overlap=0.5)
        assert boosted > base


class TestApplyConfidencePolicy:
    @patch("triage.confidence.get_triage_config")
    def test_high_confidence_label_auto_applied(self, mock_config):
        mock_config.return_value = TriageConfig()
        actions = apply_confidence_policy(
            label_suggestions=[{"label": "bug", "confidence": 0.9, "evidence": "clear bug report"}],
        )
        assert any(a.action == "apply_label" and a.target == "bug" for a in actions)

    @patch("triage.confidence.get_triage_config")
    def test_medium_confidence_label_suggested(self, mock_config):
        mock_config.return_value = TriageConfig()
        actions = apply_confidence_policy(
            label_suggestions=[{"label": "port-esp32", "confidence": 0.7, "evidence": "mentions esp32"}],
        )
        assert any(a.action == "suggest_label" and a.target == "port-esp32" for a in actions)

    @patch("triage.confidence.get_triage_config")
    def test_low_confidence_label_ignored(self, mock_config):
        mock_config.return_value = TriageConfig()
        actions = apply_confidence_policy(
            label_suggestions=[{"label": "bug", "confidence": 0.3, "evidence": "unclear"}],
        )
        assert not any(a.target == "bug" for a in actions)

    @patch("triage.confidence.get_triage_config")
    def test_high_duplicate_with_merged_ref_asserts_resolved(self, mock_config):
        mock_config.return_value = TriageConfig()
        actions = apply_confidence_policy(
            label_suggestions=[],
            duplicate_info={
                "issue_number": 123,
                "confidence": 0.95,
                "evidence": "merged PR",
                "has_merged_ref": True,
            },
        )
        assert any(a.action == "assert_resolved" for a in actions)
        assert any(a.action == "apply_label" and a.target == "proposed-close" for a in actions)

    @patch("triage.confidence.get_triage_config")
    def test_medium_duplicate_suggests_resolved(self, mock_config):
        mock_config.return_value = TriageConfig()
        actions = apply_confidence_policy(
            label_suggestions=[],
            duplicate_info={
                "issue_number": 456,
                "confidence": 0.7,
                "evidence": "similar",
                "has_merged_ref": False,
            },
        )
        assert any(a.action == "suggest_resolved" for a in actions)

    @patch("triage.confidence.get_triage_config")
    def test_no_matches_asks_for_info(self, mock_config):
        mock_config.return_value = TriageConfig()
        actions = apply_confidence_policy(
            label_suggestions=[],
            duplicate_info=None,
            codebase_found=False,
        )
        assert any(a.action == "ask_info" for a in actions)

    @patch("triage.confidence.get_triage_config")
    def test_codebase_found_prevents_ask_info(self, mock_config):
        mock_config.return_value = TriageConfig()
        actions = apply_confidence_policy(
            label_suggestions=[],
            duplicate_info=None,
            codebase_found=True,
        )
        assert not any(a.action == "ask_info" for a in actions)
