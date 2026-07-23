"""Unit tests for the deterministic evaluator."""

from app.evaluator import evaluate


def test_matching_actions():
    r = evaluate('{"action": "buy"}', '{"action": "buy"}')
    assert r.primary_valid_json and r.candidate_valid_json
    assert r.action_match is True
    assert r.is_mismatch is False


def test_different_actions():
    r = evaluate('{"action": "buy"}', '{"action": "sell"}')
    assert r.action_match is False
    assert r.primary_action == "buy"
    assert r.candidate_action == "sell"


def test_candidate_invalid_json():
    r = evaluate('{"action": "buy"}', "not json at all")
    assert r.primary_valid_json is True
    assert r.candidate_valid_json is False
    assert r.action_match is False


def test_both_invalid_json():
    r = evaluate("nope", "also nope")
    assert r.action_match is False


def test_valid_json_but_missing_action():
    r = evaluate('{"foo": 1}', '{"foo": 1}')
    # Both valid JSON, but no action -> not a match.
    assert r.primary_valid_json and r.candidate_valid_json
    assert r.primary_action is None
    assert r.action_match is False


def test_valid_json_non_object():
    r = evaluate("[1, 2, 3]", "[1, 2, 3]")
    assert r.primary_valid_json is True
    assert r.primary_action is None
    assert r.action_match is False


def test_none_inputs():
    r = evaluate(None, '{"action": "buy"}')
    assert r.primary_valid_json is False
    assert r.action_match is False


def test_action_can_be_structured():
    r = evaluate('{"action": {"type": "move", "x": 1}}',
                 '{"action": {"type": "move", "x": 1}}')
    assert r.action_match is True
