"""Confidence scoring and action policy for issue triage."""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from rag.config import get_triage_config


@dataclass
class TriageAction:
    """A single triage action with confidence."""
    action: str          # "apply_label", "suggest_label", "assert_resolved", "suggest_resolved", "ask_info"
    target: str          # label name, issue number, or description
    confidence: float    # 0.0 to 1.0
    evidence: str        # explanation of why this action was chosen


def compute_duplicate_confidence(
    similarity_score: float,
    has_merged_closing_ref: bool,
    title_overlap: float = 0.0,
) -> float:
    """Compute confidence that an issue is a duplicate/resolved.

    Args:
        similarity_score: Semantic similarity score (0-1, from RRF normalized).
        has_merged_closing_ref: Whether a merged PR explicitly closes this issue.
        title_overlap: Jaccard title word overlap (0-1).
    """
    config = get_triage_config()

    if has_merged_closing_ref:
        return config.closing_ref_merged_confidence

    # Semantic similarity → confidence mapping
    if similarity_score >= config.similarity_high:
        confidence = config.duplicate_high_confidence
    elif similarity_score >= config.similarity_medium:
        # Linear interpolation between medium and high
        t = (similarity_score - config.similarity_medium) / (
            config.similarity_high - config.similarity_medium
        )
        confidence = config.duplicate_medium_confidence + t * (
            config.duplicate_high_confidence - config.duplicate_medium_confidence
        )
    else:
        confidence = similarity_score * config.duplicate_medium_confidence / config.similarity_medium

    # Title overlap bonus
    if title_overlap > 0.3:
        confidence = min(1.0, confidence + 0.05)

    return confidence


def apply_confidence_policy(
    label_suggestions: List[Dict[str, Any]],
    duplicate_info: Optional[Dict[str, Any]] = None,
    codebase_found: bool = False,
) -> List[TriageAction]:
    """Apply confidence thresholds to produce triage actions.

    Args:
        label_suggestions: List of {label, confidence, evidence} dicts.
        duplicate_info: {issue_number, confidence, evidence, has_merged_ref} or None.
        codebase_found: Whether codebase analysis found related code.

    Returns:
        List of TriageAction instances.
    """
    config = get_triage_config()
    actions = []

    # Label actions
    for suggestion in label_suggestions:
        confidence = suggestion.get("confidence", 0.0)
        label = suggestion["label"]
        evidence = suggestion.get("evidence", "")

        if confidence >= config.label_auto_apply:
            actions.append(TriageAction(
                action="apply_label",
                target=label,
                confidence=confidence,
                evidence=evidence,
            ))
        elif confidence >= config.label_suggest:
            actions.append(TriageAction(
                action="suggest_label",
                target=label,
                confidence=confidence,
                evidence=evidence,
            ))

    # Duplicate/resolved actions
    if duplicate_info:
        confidence = duplicate_info.get("confidence", 0.0)
        issue_num = duplicate_info.get("issue_number", "?")
        evidence = duplicate_info.get("evidence", "")
        has_merged = duplicate_info.get("has_merged_ref", False)

        if confidence >= config.duplicate_high_confidence:
            if has_merged:
                actions.append(TriageAction(
                    action="assert_resolved",
                    target=str(issue_num),
                    confidence=confidence,
                    evidence=evidence,
                ))
                actions.append(TriageAction(
                    action="apply_label",
                    target="proposed-close",
                    confidence=confidence,
                    evidence=f"Resolved by PR linked to #{issue_num}",
                ))
            else:
                actions.append(TriageAction(
                    action="assert_resolved",
                    target=str(issue_num),
                    confidence=confidence,
                    evidence=evidence,
                ))
        elif confidence >= config.duplicate_medium_confidence:
            actions.append(TriageAction(
                action="suggest_resolved",
                target=str(issue_num),
                confidence=confidence,
                evidence=evidence,
            ))

    # If nothing found, suggest asking for more info
    if not actions and not codebase_found:
        actions.append(TriageAction(
            action="ask_info",
            target="",
            confidence=0.0,
            evidence="No similar issues, reviews, or codebase matches found.",
        ))

    return actions
