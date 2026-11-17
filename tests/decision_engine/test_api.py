"""API tests with a stub model (no weights)."""
import time

import pytest
from fastapi.testclient import TestClient

from decision_engine.api import _is_loopback, create_app
from decision_engine.confidence_policy import TaskPolicy

TOKEN = "test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
POL = {"agent_route": TaskPolicy(False, 0.8, 0.5), "dq_category": TaskPolicy(False, 0.8, 0.5)}


class Stub:
    checkpoint = "stub"

    def __init__(self, label="DATA_QUALITY", conf=0.9, delay=0.0):
        self.label, self.conf, self.delay = label, conf, delay

    def predict(self, body, questions):
        time.sleep(self.delay)
        (q,) = questions
        return {"answers": {q: {"choice": self.label, "answer_confidence": self.conf, "noul": 0.1}}}

    def info(self):
        return {"checkpoint": "stub", "hosted_api": False}


@pytest.fixture
def client():
    with TestClient(create_app(Stub(), POL, token=TOKEN)) as c:
        yield c


def test_refuses_to_start_without_token():
    with pytest.raises(RuntimeError):
        create_app(Stub(), POL, token="")


def test_health_is_open_and_ready(client):
    assert client.get("/health").json() == {"status": "ready"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong-token-xxxxxxxx"}, {"Authorization": TOKEN}])
def test_predict_requires_valid_bearer(client, headers):
    r = client.post("/predict", json={"task": "agent_route", "text": "hi"}, headers=headers)
    assert r.status_code == 401


def test_predict_returns_decision_without_echoing_text(client):
    secret_text = "Kenapa transaksi SAL00012345 ditolak?"
    r = client.post("/predict", json={"task": "agent_route", "text": secret_text}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "DATA_QUALITY" and body["action"] == "REVIEW"  # task disabled -> no ACCEPT
    assert secret_text not in r.text


@pytest.mark.parametrize("payload", [
    {"task": "run_sql", "text": "DROP TABLE dataset.customers"},
    {"task": "agent_route", "text": ""},
    {"task": "agent_route", "text": "a" * 2001},
    {"task": "agent_route"},
])
def test_invalid_input_rejected(client, payload):
    assert client.post("/predict", json=payload, headers=AUTH).status_code == 422


def test_oversized_body_rejected(client):
    r = client.post("/predict", content=b"x" * 70000, headers={**AUTH, "content-type": "application/json"})
    assert r.status_code == 413


def test_model_info_includes_policy(client):
    r = client.get("/model-info", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["policy"]["agent_route"]["enabled"] is False


def test_evaluate_scores_items(client):
    items = [{"task": "agent_route", "text": "Ada record ditolak?", "label": "DATA_QUALITY"},
             {"task": "agent_route", "text": "Berapa revenue?", "label": "KPI_QUERY"}]
    r = client.post("/evaluate", json={"items": items}, headers=AUTH)
    assert r.status_code == 200 and r.json()["accuracy"] == 0.5


def test_timeout_returns_504():
    with TestClient(create_app(Stub(delay=0.5), POL, token=TOKEN, timeout_s=0.1)) as c:
        r = c.post("/predict", json={"task": "agent_route", "text": "hi"}, headers=AUTH)
        assert r.status_code == 504


def test_model_load_failure_reports_error_and_503():
    class Broken(Stub):
        def predict(self, body, questions):
            raise MemoryError("no RAM")

    with TestClient(create_app(Broken(), POL, token=TOKEN)) as c:
        assert c.get("/health").json() == {"status": "error"}
        assert c.post("/predict", json={"task": "agent_route", "text": "hi"}, headers=AUTH).status_code == 503


@pytest.mark.parametrize("host,ok", [("127.0.0.1", True), ("localhost", True), ("::1", True),
                                     ("0.0.0.0", False), ("192.168.1.5", False)])
def test_loopback_check(host, ok):
    assert _is_loopback(host) is ok
