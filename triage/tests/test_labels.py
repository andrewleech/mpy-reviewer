"""Tests for triage label mapping."""

from triage.labels import (
    VALID_LABELS, COMPONENT_TO_LABEL, PORT_TO_LABEL,
    ISSUE_TYPE_TO_LABEL, SUBSYSTEM_TO_LABEL, resolve_labels,
)


class TestValidLabels:
    def test_valid_labels_is_nonempty(self):
        assert len(VALID_LABELS) > 0

    def test_all_component_labels_are_valid(self):
        for label in COMPONENT_TO_LABEL.values():
            if label:  # skip empty string for port_specific
                assert label in VALID_LABELS, f"{label!r} not in VALID_LABELS"

    def test_all_port_labels_are_valid(self):
        for label in PORT_TO_LABEL.values():
            assert label in VALID_LABELS, f"{label!r} not in VALID_LABELS"

    def test_all_type_labels_are_valid(self):
        for label in ISSUE_TYPE_TO_LABEL.values():
            assert label in VALID_LABELS, f"{label!r} not in VALID_LABELS"

    def test_all_subsystem_labels_are_valid(self):
        for label in SUBSYSTEM_TO_LABEL.values():
            assert label in VALID_LABELS, f"{label!r} not in VALID_LABELS"


class TestResolveLabels:
    def test_resolve_component(self):
        labels = resolve_labels(component="py_core")
        assert "py-core" in labels

    def test_resolve_port(self):
        labels = resolve_labels(port="esp32")
        assert "port-esp32" in labels

    def test_resolve_type(self):
        labels = resolve_labels(issue_type="bug")
        assert "bug" in labels

    def test_resolve_subsystem(self):
        labels = resolve_labels(subsystem="bluetooth")
        assert "bluetooth" in labels

    def test_resolve_combined(self):
        labels = resolve_labels(component="extmod", port="stm32", issue_type="enhancement")
        assert "extmod" in labels
        assert "port-stm32" in labels
        assert "enhancement" in labels

    def test_resolve_unknown_returns_empty(self):
        labels = resolve_labels(component="nonexistent")
        assert len(labels) == 0

    def test_resolve_none_returns_empty(self):
        labels = resolve_labels()
        assert len(labels) == 0

    def test_port_specific_component_returns_no_component_label(self):
        labels = resolve_labels(component="port_specific")
        assert len(labels) == 0

    def test_feature_request_maps_to_enhancement(self):
        labels = resolve_labels(issue_type="feature_request")
        assert "enhancement" in labels
