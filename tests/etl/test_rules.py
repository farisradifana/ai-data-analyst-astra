"""Rule catalog: Python and the SQL seed must agree; every code path maps to a known rule."""
import pathlib
import re

from astra_etl.rules import COLUMN_RULE, RULES
from astra_etl.spec import SPECS

MIGRATION = pathlib.Path(__file__).resolve().parents[2] / "sql/migrations/20261118120000_live_quarantine.sql"


def _sql_rules() -> dict[str, tuple[str, str | None, str]]:
    sql = MIGRATION.read_text(encoding="utf-8")
    rows = re.findall(r"\('([A-Z0-9_]+)', '([A-Z0-9_]+)', (NULL|'D\d+'), '([A-Z_]+)',", sql)
    return {r: (code, None if d == "NULL" else d.strip("'"), path) for r, code, d, path in rows}


def test_sql_seed_matches_python():
    assert _sql_rules() == {r.rule_id: (r.issue_code, r.decision, r.graduation_path) for r in RULES.values()}


def test_sql_text_matches_python():
    sql = MIGRATION.read_text(encoding="utf-8")
    for r in RULES.values():
        assert f"'{r.description}'" in sql and f"'{r.remediation}'" in sql, r.rule_id


def test_every_path_has_a_rule():
    assert set(COLUMN_RULE.values()) <= RULES.keys()
    for spec in SPECS:
        for rule_id, _ in spec.row_rules:
            assert rule_id in RULES, (spec.name, rule_id)
    assert {"DUPLICATE_PRIMARY_KEY", "ORPHAN_PARENT_QUARANTINED", "ORPHAN_KEY_NOT_IN_SOURCE",
            "EXACT_DUPLICATE_ROW"} <= RULES.keys()
