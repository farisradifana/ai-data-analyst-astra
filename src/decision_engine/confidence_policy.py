"""Confidence bands and actions.

Thresholds are NOT assumed to be probabilities of correctness. They are loaded from
config/laya_policy.json, which is written from the labeled evaluation (evaluation.py).
Until a task is calibrated and enabled, every prediction is routed to REVIEW.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "laya_policy.json"


@dataclass(frozen=True)
class TaskPolicy:
    enabled: bool
    high: float
    medium: float

    def band(self, confidence: float) -> str:
        if confidence >= self.high:
            return "HIGH"
        if confidence >= self.medium:
            return "MEDIUM"
        return "LOW"

    def action(self, confidence: float) -> str:
        """HIGH -> ACCEPT (low-risk routing only); MEDIUM -> REVIEW; LOW -> FALLBACK.

        A disabled task never auto-accepts.
        """
        b = self.band(confidence)
        if not self.enabled:
            return "REVIEW" if b != "LOW" else "FALLBACK"
        return {"HIGH": "ACCEPT", "MEDIUM": "REVIEW", "LOW": "FALLBACK"}[b]


# Conservative defaults used only when no calibrated policy file exists.
_DEFAULT = TaskPolicy(enabled=False, high=1.01, medium=0.5)


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, TaskPolicy]:
    if not path.exists():
        return {"dq_category": _DEFAULT, "agent_route": _DEFAULT}
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, TaskPolicy] = {}
    for task, cfg in raw["tasks"].items():
        high, medium = float(cfg["high"]), float(cfg["medium"])
        if not 0.0 <= medium <= high <= 1.01:
            raise ValueError(f"invalid thresholds for {task}: medium={medium} high={high}")
        out[task] = TaskPolicy(enabled=bool(cfg["enabled"]), high=high, medium=medium)
    return out
