"""Unit tests for the metrics snapshot / match-rate math."""

from app.metrics import Metrics


def test_empty_snapshot():
    m = Metrics()
    snap = m.snapshot()
    assert snap["total_requests"] == 0
    assert snap["exact_match_rate_pct"] == 0.0
    assert snap["evaluations"]["evaluated"] == 0


def test_match_rate_math():
    m = Metrics()
    m.exact_matches = 3
    m.mismatches = 1
    snap = m.snapshot()
    assert snap["evaluations"]["evaluated"] == 4
    assert snap["exact_match_rate_pct"] == 75.0


def test_shadow_counters_surface():
    m = Metrics()
    m.shadow_shed = 5
    m.shadow_timeouts = 2
    m.shadow_errors = 1
    snap = m.snapshot()
    assert snap["shadow"]["shed"] == 5
    assert snap["shadow"]["timeouts"] == 2
    assert snap["shadow"]["errors"] == 1
