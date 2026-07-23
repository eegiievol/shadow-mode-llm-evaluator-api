"""Deterministic heuristic evaluation of Primary vs Candidate outputs.

The rule (per spec):
  1. Did both models return valid, parseable JSON payloads?
  2. Extract the ``action`` key from both and assert they match exactly.

The comparison is pure and side-effect free so it is trivially unit-testable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvalResult:
    primary_valid_json: bool
    candidate_valid_json: bool
    primary_action: Any
    candidate_action: Any
    action_match: bool

    @property
    def is_mismatch(self) -> bool:
        return not self.action_match


def _parse_action(text: str | None) -> tuple[bool, Any]:
    """Return (is_valid_json, action_value).

    ``action`` is only extracted when the payload is a JSON object; otherwise
    the action is ``None``.
    """
    if text is None:
        return False, None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return False, None
    if isinstance(data, dict):
        return True, data.get("action")
    return True, None


def evaluate(primary_text: str | None, candidate_text: str | None) -> EvalResult:
    p_valid, p_action = _parse_action(primary_text)
    c_valid, c_action = _parse_action(candidate_text)

    # A match requires: both valid JSON, both expose a non-null ``action``,
    # and the two actions are exactly equal.
    action_match = (
        p_valid
        and c_valid
        and p_action is not None
        and c_action is not None
        and p_action == c_action
    )

    return EvalResult(
        primary_valid_json=p_valid,
        candidate_valid_json=c_valid,
        primary_action=p_action,
        candidate_action=c_action,
        action_match=action_match,
    )
