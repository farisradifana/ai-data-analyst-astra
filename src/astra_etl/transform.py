"""Extract + validate (no database). Pure Python, deterministic.

Per table:
  1. exact duplicate rows -> not loaded; recorded as EXACT_DUPLICATE_ROW (decision D5, keep first)
  2. every column cleaned; any CleanError -> quarantine
  3. cross-column row rules
  4. non-exact duplicate primary key -> quarantine DUPLICATE_PRIMARY_KEY
  5. foreign keys checked against the rows that passed in parent tables ->
     ORPHAN_PARENT_QUARANTINED (parent exists but is quarantined) or ORPHAN_KEY_NOT_IN_SOURCE
Every quarantined/duplicate row carries one rule_id from astra_etl.rules, the failing columns,
and depends_on (the row it waits for), so it can graduate to valid data later.
Reconciliation always holds: rows_read = loaded + quarantined + duplicate.
"""
from __future__ import annotations

import csv
import hashlib
import pathlib
from collections import Counter
from dataclasses import dataclass, field

from .clean import CleanError
from .rules import COLUMN_RULE, RULES
from .spec import SPECS, TableSpec

MAX_ISSUE_DETAIL = 500
MAX_DEPENDS_ON = 100


@dataclass
class Quarantined:
    line: int
    record_key: str | None
    rule_id: str
    failed_columns: list[str]
    issue_detail: str
    raw: dict
    depends_on: str | None = None

    @property
    def issue_code(self) -> str:
        return RULES[self.rule_id].issue_code


@dataclass
class TableResult:
    spec: TableSpec
    file_sha256: str
    rows_read: int = 0
    rows: list[tuple[int, dict]] = field(default_factory=list)  # (source line, clean row)
    quarantined: list[Quarantined] = field(default_factory=list)
    duplicates: list[Quarantined] = field(default_factory=list)  # EXACT_DUPLICATE_ROW

    @property
    def rows_loaded(self) -> int:
        return len(self.rows)

    @property
    def rows_duplicate(self) -> int:
        return len(self.duplicates)

    def rule_counts(self) -> Counter:
        return Counter(q.rule_id for q in self.quarantined + self.duplicates)


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: pathlib.Path) -> tuple[list[str], list[tuple[int, dict]]]:
    """Return header and (line number, raw row). Header is line 1; first data row is line 2."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [(i + 2, row) for i, row in enumerate(reader)]
        return list(reader.fieldnames or []), rows


def _key(raw: dict, pk: str) -> str | None:
    return (raw.get(pk) or "").strip().upper()[:64] or None


def _record(line: int, key: str | None, rule_id: str, errors: list[tuple[str, str]], raw: dict,
            depends_on: str | None = None) -> Quarantined:
    # Detail names columns and codes only, never values (values may be PII).
    detail = "; ".join(f"{col}:{code}" for col, code in errors)[:MAX_ISSUE_DETAIL]
    cols = list(dict.fromkeys(col for col, _ in errors))
    return Quarantined(line, key, rule_id, cols, detail, dict(raw),
                       depends_on[:MAX_DEPENDS_ON] if depends_on else None)


def clean_table(spec: TableSpec, raw_rows: list[tuple[int, dict]], sha: str) -> TableResult:
    res = TableResult(spec=spec, file_sha256=sha, rows_read=len(raw_rows))
    first_exact: dict[tuple, int] = {}
    first_pk: dict[str, int] = {}
    for line, raw in raw_rows:
        key = _key(raw, spec.pk)
        fingerprint = tuple(raw.get(k) for k in sorted(raw))
        if fingerprint in first_exact:
            res.duplicates.append(_record(line, key, "EXACT_DUPLICATE_ROW", [("row", "EXACT_DUPLICATE_ROW")],
                                          raw, f"row:{first_exact[fingerprint]}"))
            continue
        first_exact[fingerprint] = line

        row, errors = {}, []
        for col in spec.columns:
            try:
                row[col.target] = col.cleaner(raw.get(col.source))
            except CleanError as e:
                errors.append((col.target, e.code))
        if errors:
            res.quarantined.append(_record(line, key, COLUMN_RULE[errors[0][1]], errors, raw))
            continue
        broken = [rule_id for rule_id, ok in spec.row_rules if not ok(row)]
        if broken:
            errors = [("row", RULES[r].issue_code) for r in broken]
            res.quarantined.append(_record(line, key, broken[0], errors, raw))
            continue
        if row[spec.pk] in first_pk:
            res.quarantined.append(_record(line, key, "DUPLICATE_PRIMARY_KEY",
                                           [(spec.pk, "DUPLICATE_PRIMARY_KEY")], raw,
                                           f"row:{first_pk[row[spec.pk]]}"))
            continue
        first_pk[row[spec.pk]] = line
        res.rows.append((line, row))
    return res


def apply_foreign_keys(results: dict[str, TableResult], raw_lookup: dict[str, dict[int, dict]]) -> None:
    """Quarantine rows whose non-null FK is not among the loaded parent keys.

    A parent key that is in the source but quarantined -> ORPHAN_PARENT_QUARANTINED (graduates
    with the parent). A key absent from the parent file -> ORPHAN_KEY_NOT_IN_SOURCE.
    Self-references (employees.manager_id) are resolved iteratively, because removing a manager
    can orphan their reports.
    """
    for spec in SPECS:
        res = results[spec.name]
        if not spec.fks:
            continue
        while True:
            parents = {t for _, t, _ in spec.fks}
            loaded = {t: {r[results[t].spec.pk] for _, r in results[t].rows} for t in parents}
            held = {t: {q.record_key for q in results[t].quarantined} for t in parents}
            kept, moved = [], 0
            for line, row in res.rows:
                bad = [(col, parent) for col, parent, _nullable in spec.fks
                       if row[col] is not None and row[col] not in loaded[parent]]
                if not bad:
                    kept.append((line, row))
                    continue
                waiting = [f"{parent}:{row[col]}" for col, parent in bad if row[col] in held[parent]]
                rule_id = "ORPHAN_PARENT_QUARANTINED" if len(waiting) == len(bad) else "ORPHAN_KEY_NOT_IN_SOURCE"
                res.quarantined.append(_record(line, row[spec.pk], rule_id,
                                               [(col, "ORPHAN_FOREIGN_KEY") for col, _ in bad],
                                               raw_lookup[spec.name][line], ";".join(waiting) or None))
                moved += 1
            res.rows = kept
            self_ref = spec.name in parents
            if not moved or not self_ref:
                break


def transform(raw_dir: pathlib.Path) -> dict[str, TableResult]:
    results: dict[str, TableResult] = {}
    raw_lookup: dict[str, dict[int, dict]] = {}
    for spec in SPECS:
        path = raw_dir / spec.file
        header, raw_rows = read_csv(path)
        missing = [c.source for c in spec.columns if c.source not in header]
        if missing:
            raise RuntimeError(f"{spec.file}: missing columns {missing}")
        results[spec.name] = clean_table(spec, raw_rows, sha256_file(path))
        raw_lookup[spec.name] = dict(raw_rows)
    apply_foreign_keys(results, raw_lookup)
    for res in results.values():
        assert res.rows_loaded + len(res.quarantined) + res.rows_duplicate == res.rows_read, res.spec.name
        assert all(q.rule_id in RULES for q in res.quarantined + res.duplicates), res.spec.name
    return results
