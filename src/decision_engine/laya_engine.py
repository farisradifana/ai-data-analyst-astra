"""Decision engine: Laya prediction -> confidence policy -> decision, with deterministic fallback.

Laya only selects from closed label sets. It never runs SQL, mutates data or sends messages.
Any Laya error or low confidence falls back to fallback.py rules and is logged.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from . import fallback
from .confidence_policy import TaskPolicy, load_policy
from .decision_schemas import DQ_CRITERIA, ROUTE_CRITERIA, Decision, PredictRequest

log = logging.getLogger("decision_engine.laya")

TASK_QUESTIONS: dict[str, dict[str, Any]] = {
    "dq_category": {
        "type": "choice",
        "instructions": "Classify the type of this data quality incident.",
        "criteria": DQ_CRITERIA,
    },
    "agent_route": {
        "type": "choice",
        "instructions": "Classify what the user is asking the analytics assistant to do.",
        "criteria": ROUTE_CRITERIA,
    },
}


def laya_choice(manager: Any, task: str, text: str) -> tuple[str, float]:
    """Return (label, confidence) from Laya. Raises on any model error or out-of-set label."""
    q = {task: TASK_QUESTIONS[task]}
    res = manager.predict(text, q)
    ans = res["answers"][task]
    label = ans["choice"]
    if label not in TASK_QUESTIONS[task]["criteria"]:
        raise ValueError(f"laya returned out-of-set label {label!r}")
    # answer_confidence = max(p) over the closed options (upstream gating field).
    # ans["confidence"] = 1 - normalised entropy; kept in eval logs, not used for gating.
    conf = ans.get("answer_confidence")
    if conf is None:
        probs = ans.get("probabilities") or {}
        conf = max(probs.values()) if probs else 0.0
    return label, float(conf)


class DecisionEngine:
    def __init__(self, manager: Any, policy: dict[str, TaskPolicy] | None = None) -> None:
        self.manager = manager
        self.policy = policy or load_policy()

    def decide(self, req: PredictRequest) -> Decision:
        rid = req.request_id or uuid.uuid4().hex[:16]
        pol = self.policy[req.task]
        t0 = time.perf_counter()
        err: str | None = None
        try:
            label, conf = laya_choice(self.manager, req.task, req.text)
            band, action = pol.band(conf), pol.action(conf)
            source, fb_used = "laya", False
            if action == "FALLBACK":
                label, source, fb_used = fallback.classify(req.task, req.text), "rule_fallback", True
        except Exception as exc:  # inference failure must not crash the caller; it is logged and surfaced
            err = f"{type(exc).__name__}: {exc}"[:300]
            log.error("laya inference failed request_id=%s task=%s error=%s", rid, req.task, err)
            label, conf, band, action = fallback.classify(req.task, req.text), 0.0, "LOW", "REVIEW"
            source, fb_used = "rule_fallback", True
        d = Decision(
            request_id=rid, task=req.task, label=label, confidence=round(conf, 4), band=band,
            action=action, source=source, checkpoint=getattr(self.manager, "checkpoint", None),
            latency_ms=round((time.perf_counter() - t0) * 1000, 1), fallback_used=fb_used, error=err,
        )
        # Structured log without the input text (may contain record details).
        log.info(json.dumps({"event": "laya_decision", "run_id": req.run_id, **d.model_dump()}))
        return d
