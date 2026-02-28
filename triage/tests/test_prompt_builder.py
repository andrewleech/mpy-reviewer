"""Tests for triage prompt builder."""

import json
import os
from triage.prompt_builder import (
    TriageContext, TriagePromptBuilder, TRIAGE_STYLE_GUIDE, get_triage_builder,
)


class TestTriagePromptBuilder:
    def setup_method(self):
        self.builder = TriagePromptBuilder()

    def test_build_triage_prompt_contains_issue(self):
        context = TriageContext(
            issue_number=123,
            issue_title="Test issue",
            issue_body="This is a test",
            issue_labels=["bug"],
            issue_state="open",
        )
        prompt = self.builder.build_triage_prompt(context)
        assert "Issue #123" in prompt
        assert "Test issue" in prompt
        assert "This is a test" in prompt

    def test_build_triage_prompt_contains_style_guide(self):
        context = TriageContext(
            issue_number=1,
            issue_title="t",
            issue_body="b",
            issue_labels=[],
            issue_state="open",
        )
        prompt = self.builder.build_triage_prompt(context)
        assert "dpgeorge" in prompt
        assert "terse" in prompt.lower() or "direct" in prompt.lower()

    def test_build_triage_prompt_includes_similar_issues(self):
        context = TriageContext(
            issue_number=1,
            issue_title="t",
            issue_body="b",
            issue_labels=[],
            issue_state="open",
            similar_issues=[
                {"issue_number": 50, "title": "Related issue", "state": "closed",
                 "labels": "[]", "rrf_score": 0.5, "body": "some body", "repo": "micropython/micropython"},
            ],
        )
        prompt = self.builder.build_triage_prompt(context)
        assert "Similar Issues" in prompt
        assert "#50" in prompt

    def test_build_triage_prompt_includes_closing_refs(self):
        context = TriageContext(
            issue_number=1,
            issue_title="t",
            issue_body="b",
            issue_labels=[],
            issue_state="open",
            closing_refs=[
                {"pr_number": 999, "pr_repo": "micropython/micropython", "pr_merged": True},
            ],
        )
        prompt = self.builder.build_triage_prompt(context)
        assert "Closing References" in prompt
        assert "#999" in prompt
        assert "merged" in prompt

    def test_build_triage_prompt_includes_valid_labels_list(self):
        context = TriageContext(
            issue_number=1,
            issue_title="t",
            issue_body="b",
            issue_labels=[],
            issue_state="open",
        )
        prompt = self.builder.build_triage_prompt(context)
        assert "py-core" in prompt
        assert "port-esp32" in prompt

    def test_build_triage_prompt_task_section_present(self):
        context = TriageContext(
            issue_number=1,
            issue_title="t",
            issue_body="b",
            issue_labels=[],
            issue_state="open",
        )
        prompt = self.builder.build_triage_prompt(context)
        assert "Your Task" in prompt
        assert "Classification" in prompt
        assert "Duplicate" in prompt
        assert "Response" in prompt


class TestWriteTriageExampleFiles:
    def test_write_creates_files(self, tmp_path):
        builder = TriagePromptBuilder()
        issues = [
            {"issue_number": 10, "title": "Test", "state": "open",
             "labels": "[]", "body": "body text", "repo": "micropython/micropython"},
        ]
        temp_dir, file_infos = builder.write_triage_example_files(
            issues, temp_dir=str(tmp_path),
        )
        assert len(file_infos) == 1
        assert os.path.exists(file_infos[0]["path"])
        assert file_infos[0]["size_bytes"] > 0

    def test_write_content_is_readable(self, tmp_path):
        builder = TriagePromptBuilder()
        issues = [
            {"issue_number": 42, "title": "UART bug", "state": "closed",
             "labels": json.dumps(["bug"]), "body": "UART fails", "repo": "micropython/micropython"},
        ]
        temp_dir, file_infos = builder.write_triage_example_files(
            issues, temp_dir=str(tmp_path),
        )
        content = open(file_infos[0]["path"]).read()
        assert "UART bug" in content
        assert "#42" in content


class TestGetTriageBuilder:
    def test_returns_singleton(self):
        b1 = get_triage_builder()
        b2 = get_triage_builder()
        assert b1 is b2
