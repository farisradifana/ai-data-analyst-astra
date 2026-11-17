import pytest
from pydantic import ValidationError

from decision_engine.decision_schemas import (
    DQ_CRITERIA,
    MAX_TEXT_CHARS,
    ROUTE_CRITERIA,
    DQCategory,
    PredictRequest,
    RouteCategory,
)


def test_criteria_cover_exactly_the_closed_label_sets():
    assert set(DQ_CRITERIA) == {c.value for c in DQCategory}
    assert set(ROUTE_CRITERIA) == {c.value for c in RouteCategory}


def test_request_rejects_empty_and_too_long_text():
    with pytest.raises(ValidationError):
        PredictRequest(task="agent_route", text="")
    with pytest.raises(ValidationError):
        PredictRequest(task="agent_route", text="a" * (MAX_TEXT_CHARS + 1))


def test_request_rejects_unknown_task():
    with pytest.raises(ValidationError):
        PredictRequest(task="run_sql", text="DROP TABLE dataset.customers")
