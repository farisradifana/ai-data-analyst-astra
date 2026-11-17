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
Active corrections (dataset.quarantine_correction) are overlaid on the raw rows before step 1;
the source files are never changed. record_key always stays the key from the source file.
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
    corrected_columns: list[str] = field(default_factory=list)

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
    source_keys: dict[int, str | None] = field(default_factory=dict)  # line -> key in source file
    corrected: dict[int, list[str]] = field(default_factory=dict)     # line -> corrected columns
    correction_lines: dict[int, list[int]] = field(default_factory=dict)  # correction_id -> lines
    correction_outcome: dict[int, str] = field(default_factory=dict)      # correction_id -> outcome

    @property
    def rows_loaded(self) -> int:
        return len(self.rows)

    @property
    def rows_duplicate(self) -> int:
        return len(self.duplicates)

    def loaded_keys(self) -> set[str]:
        """Keys that are now valid: source key and (possibly corrected) primary key of loaded rows."""
        keys = {str(row[self.spec.pk]) for _, row in self.rows}
        keys |= {k for line, _ in self.rows if (k := self.source_keys.get(line))}
        return keys

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


@dataclass(frozen=True)
class Correction:
    correction_id: int
    table_name: str
    record_key: str
    source_row_number: int | None
    column_name: str
    value: str | None


def _key(raw: dict, pk: str) -> str | None:
    return (raw.get(pk) or "").strip().upper()[:64] or None


def apply_corrections(res: TableResult, header: list[str], raw_rows: list[tuple[int, dict]],
                      corrections: list[Correction]) -> None:
    """Overlay corrections on raw rows in place. Matches on the source key (+ line if given)."""
    by_key: dict[str, list[int]] = {}
    for line, raw in raw_rows:
        key = _key(raw, res.spec.pk)
        res.source_keys[line] = key
        if key:
            by_key.setdefault(key, []).append(line)
    rows = dict(raw_rows)
    for c in sorted(corrections, key=lambda c: c.correction_id):
        if c.column_name not in header:
            res.correction_outcome[c.correction_id] = "COLUMN_UNKNOWN"
            continue
        lines = [ln for ln in by_key.get(c.record_key.strip().upper(), [])
                 if c.source_row_number in (None, ln)]
        if not lines:
            res.correction_outcome[c.correction_id] = "KEY_NOT_FOUND"
            continue
        for ln in lines:
            rows[ln][c.column_name] = "" if c.value is None else c.value
            res.corrected.setdefault(ln, []).append(c.column_name)
        res.correction_lines[c.correction_id] = lines


def _record(line: int, key: str | None, rule_id: str, errors: list[tuple[str, str]], raw: dict,
            depends_on: str | None = None, corrected: list[str] | None = None) -> Quarantined:
    # Detail names columns and codes only, never values (values may be PII).
    detail = "; ".join(f"{col}:{code}" for col, code in errors)[:MAX_ISSUE_DETAIL]
    cols = list(dict.fromkeys(col for col, _ in errors))
    return Quarantined(line, key, rule_id, cols, detail, dict(raw),
                       depends_on[:MAX_DEPENDS_ON] if depends_on else None, list(corrected or []))


def clean_table(spec: TableSpec, raw_rows: list[tuple[int, dict]], sha: str, header: list[str] | None = None,
                corrections: list[Correction] | None = None) -> TableResult:
    res = TableResult(spec=spec, file_sha256=sha, rows_read=len(raw_rows))
    if header is None:
        header = list(raw_rows[0][1]) if raw_rows else []
    apply_corrections(res, header, raw_rows, corrections or [])
    first_exact: dict[tuple, int] = {}
    first_pk: dict[str, int] = {}

    def record(line, key, rule_id, errors, raw, depends_on=None):
        return _record(line, key, rule_id, errors, raw, depends_on, res.corrected.get(line))

    for line, raw in raw_rows:
        key = res.source_keys[line]
        fingerprint = tuple(raw.get(k) for k in sorted(raw))
        if fingerprint in first_exact:
            res.duplicates.append(record(line, key, "EXACT_DUPLICATE_ROW", [("row", "EXACT_DUPLICATE_ROW")],
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
            res.quarantined.append(record(line, key, COLUMN_RULE[errors[0][1]], errors, raw))
            continue
        broken = [rule_id for rule_id, ok in spec.row_rules if not ok(row)]
        if broken:
            errors = [("row", RULES[r].issue_code) for r in broken]
            res.quarantined.append(record(line, key, broken[0], errors, raw))
            continue
        if row[spec.pk] in first_pk:
            res.quarantined.append(record(line, key, "DUPLICATE_PRIMARY_KEY",
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
            for t in parents:  # a parent whose key was corrected is held under its new key too
                held[t] |= {str(q.raw.get(results[t].spec.pk) or "").strip().upper()
                            for q in results[t].quarantined}
            kept, moved = [], 0
            for line, row in res.rows:
                bad = [(col, parent) for col, parent, _nullable in spec.fks
                       if row[col] is not None and row[col] not in loaded[parent]]
                if not bad:
                    kept.append((line, row))
                    continue
                waiting = [f"{parent}:{row[col]}" for col, parent in bad if row[col] in held[parent]]
                rule_id = "ORPHAN_PARENT_QUARANTINED" if len(waiting) == len(bad) else "ORPHAN_KEY_NOT_IN_SOURCE"
                res.quarantined.append(_record(line, res.source_keys.get(line), rule_id,
                                               [(col, "ORPHAN_FOREIGN_KEY") for col, _ in bad],
                                               raw_lookup[spec.name][line], ";".join(waiting) or None,
                                               res.corrected.get(line)))
                moved += 1
            res.rows = kept
            self_ref = spec.name in parents
            if not moved or not self_ref:
                break


def transform(raw_dir: pathlib.Path, corrections: list[Correction] | None = None) -> dict[str, TableResult]:
    results: dict[str, TableResult] = {}
    raw_lookup: dict[str, dict[int, dict]] = {}
    for spec in SPECS:
        path = raw_dir / spec.file
        header, raw_rows = read_csv(path)
        missing = [c.source for c in spec.columns if c.source not in header]
        if missing:
            raise RuntimeError(f"{spec.file}: missing columns {missing}")
        mine = [c for c in corrections or [] if c.table_name == spec.name]
        results[spec.name] = clean_table(spec, raw_rows, sha256_file(path), header, mine)
        raw_lookup[spec.name] = dict(raw_rows)
    apply_foreign_keys(results, raw_lookup)
    for res in results.values():
        held = {q.line for q in res.quarantined}
        for cid, lines in res.correction_lines.items():
            res.correction_outcome[cid] = "STILL_QUARANTINED" if held.intersection(lines) else "LOADED"
    for res in results.values():
        assert res.rows_loaded + len(res.quarantined) + res.rows_duplicate == res.rows_read, res.spec.name
        assert all(q.rule_id in RULES for q in res.quarantined + res.duplicates), res.spec.name
    return results
