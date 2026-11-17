import pytest

from decision_engine import fallback
from decision_engine.decision_schemas import DQCategory, RouteCategory


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Kolom product_id kosong, padahal wajib diisi.", "MISSING_REQUIRED_FIELD"),
        ("Customer appears twice with identical values.", "DUPLICATE_RECORD"),
        ("Expense amount is -50000; expenses must be positive.", "BUSINESS_RULE_VIOLATION"),
        ("Casting active_flag 'MAYBE' to BOOLEAN raised a conversion error.", "TYPE_CONVERSION_ERROR"),
        ("something odd happened", "UNKNOWN_ERROR"),
    ],
)
def test_dq_rules(text, expected):
    assert fallback.classify("dq_category", text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Berapa total revenue bulan ini?", "KPI_QUERY"),
        ("Ada berapa record yang ditolak saat processing terakhir?", "DATA_QUALITY"),
        ("Tolong proses ulang data penjualan yang ditolak kemarin.", "REPROCESSING_REQUEST"),
        ("Kapan terakhir data di-refresh?", "PIPELINE_STATUS"),
        ("asdfgh qwerty", "UNKNOWN"),
    ],
)
def test_route_rules(text, expected):
    assert fallback.classify("agent_route", text) == expected


def test_fallback_only_returns_closed_labels():
    for t in ["", "x", "Kenapa?", "error", "total"]:
        assert fallback.classify("dq_category", t) in {c.value for c in DQCategory}
        assert fallback.classify("agent_route", t) in {c.value for c in RouteCategory}


def test_unknown_task_raises():
    with pytest.raises(ValueError):
        fallback.classify("sql_exec", "DROP TABLE x")
