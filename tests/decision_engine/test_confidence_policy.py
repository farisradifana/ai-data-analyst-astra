import json

import pytest

from decision_engine.confidence_policy import TaskPolicy, load_policy


def test_bands_and_actions_when_enabled():
    p = TaskPolicy(enabled=True, high=0.6, medium=0.3)
    assert (p.band(0.9), p.action(0.9)) == ("HIGH", "ACCEPT")
    assert (p.band(0.6), p.action(0.6)) == ("HIGH", "ACCEPT")
    assert (p.band(0.45), p.action(0.45)) == ("MEDIUM", "REVIEW")
    assert (p.band(0.1), p.action(0.1)) == ("LOW", "FALLBACK")


def test_disabled_task_never_auto_accepts():
    p = TaskPolicy(enabled=False, high=0.6, medium=0.3)
    assert p.action(0.99) == "REVIEW"
    assert p.action(0.05) == "FALLBACK"


def test_missing_policy_file_is_conservative(tmp_path):
    pol = load_policy(tmp_path / "absent.json")
    for task in ("dq_category", "agent_route"):
        assert pol[task].enabled is False
        assert pol[task].action(1.0) == "REVIEW"


def test_invalid_thresholds_rejected(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"tasks": {"agent_route": {"enabled": True, "high": 0.2, "medium": 0.5}}}))
    with pytest.raises(ValueError):
        load_policy(f)
