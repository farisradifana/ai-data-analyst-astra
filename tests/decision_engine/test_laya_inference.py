"""Real local inference with the cached multilingual checkpoint.

Opt-in because it loads ~650 MB of weights (35 s+):  pytest -m laya
"""
import pytest

from decision_engine.decision_schemas import DQCategory, PredictRequest, RouteCategory
from decision_engine.laya_engine import DecisionEngine
from decision_engine.model_manager import ModelManager

pytestmark = pytest.mark.laya


@pytest.fixture(scope="module")
def engine():
    return DecisionEngine(ModelManager("multilingual"))


def test_model_info_is_local_and_pinned(engine):
    info = engine.manager.info()
    assert info["hosted_api"] is False and info["vega_lane"] is False
    assert info["pinned_revision"] and len(info["pinned_revision"]) == 40


@pytest.mark.parametrize("text", ["Ada berapa record yang ditolak saat processing terakhir?",
                                  "Which validation rules failed most often in the customers table?"])
def test_route_returns_closed_label(engine, text):
    d = engine.decide(PredictRequest(task="agent_route", text=text))
    assert d.label in {c.value for c in RouteCategory}
    assert 0.0 <= d.confidence <= 1.0 and d.error is None


def test_indonesian_dq_incident_returns_closed_label(engine):
    d = engine.decide(PredictRequest(task="dq_category", text="Baris karyawan EMP00321 tercatat dua kali dengan isi yang sama persis."))
    assert d.label in {c.value for c in DQCategory}


def test_committed_policy_never_auto_accepts(engine):
    d = engine.decide(PredictRequest(task="agent_route", text="Berapa total revenue bulan ini?"))
    assert d.action != "ACCEPT"
