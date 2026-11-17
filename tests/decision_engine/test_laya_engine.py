"""Engine behaviour with a stub model (no weights needed)."""
from decision_engine.confidence_policy import TaskPolicy
from decision_engine.decision_schemas import PredictRequest
from decision_engine.laya_engine import DecisionEngine


class StubManager:
    checkpoint = "stub"

    def __init__(self, label=None, conf=0.9, exc=None):
        self.label, self.conf, self.exc = label, conf, exc

    def predict(self, body, questions):
        if self.exc:
            raise self.exc
        (task,) = questions
        # Mirrors laya 0.4.35: answer_confidence = max(p); confidence = 1 - normalised entropy.
        return {"answers": {task: {"choice": self.label, "answer_confidence": self.conf, "confidence": 0.0}}}


POL = {"agent_route": TaskPolicy(True, 0.6, 0.3), "dq_category": TaskPolicy(True, 0.6, 0.3)}


def test_high_confidence_accepted():
    d = DecisionEngine(StubManager("KPI_QUERY", 0.9), POL).decide(PredictRequest(task="agent_route", text="Berapa revenue?"))
    assert (d.label, d.action, d.source, d.fallback_used) == ("KPI_QUERY", "ACCEPT", "laya", False)


def test_medium_confidence_goes_to_review():
    d = DecisionEngine(StubManager("KPI_QUERY", 0.4), POL).decide(PredictRequest(task="agent_route", text="x"))
    assert (d.band, d.action) == ("MEDIUM", "REVIEW")


def test_low_confidence_uses_rule_fallback():
    d = DecisionEngine(StubManager("KPI_QUERY", 0.1), POL).decide(
        PredictRequest(task="agent_route", text="Tolong proses ulang tabel inventory"))
    assert (d.action, d.source, d.label) == ("FALLBACK", "rule_fallback", "REPROCESSING_REQUEST")


def test_model_error_falls_back_and_flags_review():
    d = DecisionEngine(StubManager(exc=RuntimeError("OOM")), POL).decide(
        PredictRequest(task="dq_category", text="Customer appears twice, identical rows"))
    assert d.fallback_used and d.action == "REVIEW" and d.label == "DUPLICATE_RECORD"
    assert d.error and "OOM" in d.error


def test_out_of_set_label_is_rejected():
    d = DecisionEngine(StubManager("DROP_TABLE", 0.99), POL).decide(PredictRequest(task="agent_route", text="hi"))
    assert d.source == "rule_fallback" and d.label != "DROP_TABLE"
