"""In-memory metrics store.

All mutation happens from within the single-threaded asyncio event loop
(request handlers and shadow workers), so plain integer counters are safe:
each ``+= 1`` is atomic between ``await`` points and no counter is read and
then written across an await.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Metrics:
    total_requests: int = 0

    # Shadow lifecycle
    shadow_enqueued: int = 0
    shadow_completed: int = 0
    shadow_shed: int = 0        # dropped because the bounded queue was full
    shadow_skipped: int = 0     # not mirrored due to shadow_percentage sampling
    shadow_errors: int = 0      # candidate call raised
    shadow_timeouts: int = 0    # candidate call exceeded its deadline

    # Evaluation outcomes
    exact_matches: int = 0
    mismatches: int = 0

    def record_request(self) -> None:
        self.total_requests += 1

    def snapshot(self) -> dict:
        evaluated = self.exact_matches + self.mismatches
        match_rate = (self.exact_matches / evaluated * 100.0) if evaluated else 0.0
        return {
            "total_requests": self.total_requests,
            "shadow": {
                "enqueued": self.shadow_enqueued,
                "completed": self.shadow_completed,
                "shed": self.shadow_shed,
                "skipped": self.shadow_skipped,
                "errors": self.shadow_errors,
                "timeouts": self.shadow_timeouts,
            },
            "evaluations": {
                "evaluated": evaluated,
                "exact_matches": self.exact_matches,
                "mismatches": self.mismatches,
            },
            "exact_match_rate_pct": round(match_rate, 2),
        }
