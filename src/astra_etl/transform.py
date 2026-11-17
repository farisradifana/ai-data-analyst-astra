"""Extract + validate (no database access). Pure Python, deterministic.

Each run validates, per table (parents first), one list of candidate rows:
  1. every row still in quarantine (raw_record as edited by analysts), then
  2. the rows of source files the ETL has not read before (each file is read only once).
Per candidate:
  a. exact copy of an earlier candidate (raw values)          -> EXACT_DUPLICATE_ROW (D5, keep first)
  b. any column fails its cleaner                             -> column rule (rules.COLUMN_RULE)
  c. cross-column row rules                                   -> rule named in spec.row_rules
  d. key already taken by an earlier passing candidate        -> DUPLICATE_PRIMARY_KEY
  e. key already loaded in the database: same clean values    -> EXACT_DUPLICATE_ROW
                                         different values     -> DUPLICATE_PRIMARY_KEY (strict)
  f. foreign keys: parent loaded (database or this run)       -> ok
                   parent in quarantine                       -> ORPHAN_PARENT_QUARANTINED
                   parent nowhere                             -> ORPHAN_KEY_NOT_IN_SOURCE
A candidate that passes is loaded. A quarantined candidate that passes graduates (load.py archives
and deletes it); one that fails keeps its quarantine row with refreshed labels.
Reconciliation always holds:
  per new file:   rows_read = loaded + quarantined + duplicate
  per table:      quarantine rows checked = graduated + still open + dropped as duplicate
"""
from __future__ import annotations

import csv
import hashlib
import pathlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

from .clean import CleanError
from .rules import COLUMN_RULE, RULES
from .spec import SPEC_BY_NAME, SPECS, TableSpec

MAX_ISSUE_DETAIL = 500
MAX_DEPENDS_ON = 100

# (table, keys) -> {key: tuple of clean values in spec.columns order} for keys already loaded.
ExistingRows = Callable[[str, list[str]], dict[str, tuple]]


@dataclass(frozen=True)
class SourceFile:
    table: str
    name: str             # path relative to raw-data, forward slashes
    sha256: str
    rows: tuple           # ((line, raw dict), ...); header is line 1


@dataclass
class OpenRecord:
    """A row already in dataset.quarantine_record."""
    quarantine_id: int
    source_file: str
    line: int
    raw: dict
    edited_columns: list[str] = field(default_factory=list)


@dataclass
class Quarantined:
    source_file: str
    line: int
    record_key: str | None
    rule_id: str
    failed_columns: list[str]
    issue_detail: str
    raw: dict
    depends_on: str | None = None
    quarantine_id: int | None = None      # set when the row was already in quarantine
    edited_columns: list[str] = field(default_factory=list)

    @property
    def issue_code(self) -> str:
        return RULES[self.rule_id].issue_code


@dataclass
class Loaded:
    source_file: str
    line: int
    row: dict
    quarantine_id: int | None = None      # set when the row graduates from quarantine


@dataclass
class FileStats:
    name: str
    sha256: str
    rows_read: int
    rows_loaded: int = 0
    rows_quarantined: int = 0
    rows_duplicate: int = 0


@dataclass
class TableResult:
    spec: TableSpec
    files: list[FileStats] = field(default_factory=list)
    rows: list[Loaded] = field(default_factory=list)
    quarantined: list[Quarantined] = field(default_factory=list)  # new rows and rows still open
    duplicates: list[Quarantined] = field(default_factory=list)   # EXACT_DUPLICATE_ROW, never loaded
    rechecked: int = 0                                            # quarantine rows checked this run

    @property
    def graduated(self) -> list[int]:
        return [r.quarantine_id for r in self.rows if r.quarantine_id is not None]

    @property
    def still_open(self) -> list[Quarantined]:
        return [q for q in self.quarantined if q.quarantine_id is not None]

    @property
    def new_quarantine(self) -> list[Quarantined]:
        return [q for q in self.quarantined if q.quarantine_id is None]

    def rule_counts(self, new_only: bool = True) -> Counter:
        items = self.quarantined + self.duplicates
        return Counter(q.rule_id for q in items if not new_only or q.quarantine_id is None)

    def loaded_keys(self) -> set[str]:
        return {r.row[self.spec.pk] for r in self.rows}

    def held_keys(self) -> set[str]:
        """Keys of rows in quarantine after this run (parents that children may wait for)."""
        return {k for q in self.quarantined if (k := q.record_key)}


# --- files -----------------------------------------------------------------------------------

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


def discover(raw_dir: pathlib.Path) -> dict[str, list[tuple[str, pathlib.Path]]]:
    """Source files per table: raw-data/<table>.csv first, then raw-data/<table>/*.csv by name."""
    found: dict[str, list[tuple[str, pathlib.Path]]] = {}
    for spec in SPECS:
        paths = [raw_dir / spec.file] if (raw_dir / spec.file).is_file() else []
        folder = raw_dir / spec.name
        if folder.is_dir():
            paths += sorted(p for p in folder.glob("*.csv") if p.is_file())
        found[spec.name] = [(p.relative_to(raw_dir).as_posix(), p) for p in paths]
    return found


def read_source(table: str, name: str, path: pathlib.Path) -> SourceFile:
    header, rows = read_csv(path)
    missing = [c.source for c in SPEC_BY_NAME[table].columns if c.source not in header]
    if missing:
        raise RuntimeError(f"{name}: missing columns {missing}")
    return SourceFile(table, name, sha256_file(path), tuple(rows))


# --- validation ------------------------------------------------------------------------------

def _key(raw: dict, pk: str) -> str | None:
    return (raw.get(pk) or "").strip().upper()[:64] or None


def _label(cand: dict, rule_id: str, errors: list[tuple[str, str]], depends_on: str | None = None) -> Quarantined:
    # Detail names columns and codes only, never values (values may be PII).
    detail = "; ".join(f"{col}:{code}" for col, code in errors)[:MAX_ISSUE_DETAIL]
    cols = list(dict.fromkeys(col for col, _ in errors))
    return Quarantined(cand["file"], cand["line"], _key(cand["raw"], cand["pk_source"]), rule_id, cols, detail,
                       dict(cand["raw"]), depends_on[:MAX_DEPENDS_ON] if depends_on else None,
                       cand["qid"], list(cand["edited"]))


def _candidates(spec: TableSpec, open_records: list[OpenRecord], files: list[SourceFile]) -> list[dict]:
    pk_source = next(c.source for c in spec.columns if c.target == spec.pk)
    out = [{"file": o.source_file, "line": o.line, "raw": o.raw, "qid": o.quarantine_id,
            "edited": o.edited_columns, "pk_source": pk_source}
           for o in sorted(open_records, key=lambda o: (o.source_file, o.line))]
    for f in files:
        out += [{"file": f.name, "line": line, "raw": raw, "qid": None, "edited": [], "pk_source": pk_source}
                for line, raw in f.rows]
    return out


def clean_table(spec: TableSpec, candidates: list[dict], db_keys: set[str],
                existing: ExistingRows) -> tuple[TableResult, list[tuple[dict, dict]]]:
    """Steps a-e. Returns the result and the passing (candidate, clean row) pairs (FKs not checked)."""
    res = TableResult(spec=spec, rechecked=sum(1 for c in candidates if c["qid"] is not None))
    first_exact: dict[tuple, dict] = {}
    first_pk: dict[str, dict] = {}
    passing: list[tuple[dict, dict]] = []
    for cand in candidates:
        raw = cand["raw"]
        fingerprint = tuple((k, raw.get(k)) for k in sorted(raw))
        if fingerprint in first_exact:
            first = first_exact[fingerprint]
            res.duplicates.append(_label(cand, "EXACT_DUPLICATE_ROW", [("row", "EXACT_DUPLICATE_ROW")],
                                         f"row:{first['file']}:{first['line']}"))
            continue
        first_exact[fingerprint] = cand

        row, errors = {}, []
        for col in spec.columns:
            try:
                row[col.target] = col.cleaner(raw.get(col.source))
            except CleanError as e:
                errors.append((col.target, e.code))
        if errors:
            res.quarantined.append(_label(cand, COLUMN_RULE[errors[0][1]], errors))
            continue
        broken = [rule_id for rule_id, ok in spec.row_rules if not ok(row)]
        if broken:
            res.quarantined.append(_label(cand, broken[0], [("row", RULES[r].issue_code) for r in broken]))
            continue
        key = row[spec.pk]
        if key in first_pk:
            first = first_pk[key]
            res.quarantined.append(_label(cand, "DUPLICATE_PRIMARY_KEY", [(spec.pk, "DUPLICATE_PRIMARY_KEY")],
                                          f"row:{first['file']}:{first['line']}"))
            continue
        first_pk[key] = cand
        passing.append((cand, row))

    taken = [row[spec.pk] for _, row in passing if row[spec.pk] in db_keys]
    loaded = existing(spec.name, taken) if taken else {}
    kept = []
    for cand, row in passing:
        key = row[spec.pk]
        if key in db_keys:
            same = loaded.get(key) == tuple(row[c.target] for c in spec.columns)
            rule = "EXACT_DUPLICATE_ROW" if same else "DUPLICATE_PRIMARY_KEY"
            target = res.duplicates if same else res.quarantined
            target.append(_label(cand, rule, [(spec.pk, rule)], f"{spec.name}:{key}"))
            continue
        kept.append((cand, row))
    return res, kept


def apply_foreign_keys(spec: TableSpec, res: TableResult, passing: list[tuple[dict, dict]],
                       results: dict[str, TableResult], db_keys: dict[str, set[str]]) -> None:
    """Step f. Parents are earlier in SPECS, so their results are final; a self-reference
    (employees.manager_id) is resolved iteratively because quarantining a manager can orphan
    their reports."""
    parents = {t for _, t, _ in spec.fks}
    while True:
        valid = {t: db_keys.get(t, set()) | ({row[spec.pk] for _, row in passing} if t == spec.name
                                             else results[t].loaded_keys()) for t in parents}
        held = {t: (res if t == spec.name else results[t]).held_keys() for t in parents}
        kept, moved = [], 0
        for cand, row in passing:
            bad = [(col, parent) for col, parent, _nullable in spec.fks
                   if row[col] is not None and row[col] not in valid[parent]]
            if not bad:
                kept.append((cand, row))
                continue
            waiting = [f"{parent}:{row[col]}" for col, parent in bad if row[col] in held[parent]]
            rule_id = "ORPHAN_PARENT_QUARANTINED" if len(waiting) == len(bad) else "ORPHAN_KEY_NOT_IN_SOURCE"
            res.quarantined.append(_label(cand, rule_id, [(col, "ORPHAN_FOREIGN_KEY") for col, _ in bad],
                                          ";".join(waiting) or None))
            moved += 1
        passing = kept
        if not moved or spec.name not in parents:
            break
    res.rows = [Loaded(c["file"], c["line"], row, c["qid"]) for c, row in passing]


def _file_stats(res: TableResult, files: list[SourceFile]) -> None:
    stats = {f.name: FileStats(f.name, f.sha256, len(f.rows)) for f in files}
    for r in res.rows:
        if r.quarantine_id is None:
            stats[r.source_file].rows_loaded += 1
    for q in res.new_quarantine:
        stats[q.source_file].rows_quarantined += 1
    for q in res.duplicates:
        if q.quarantine_id is None:
            stats[q.source_file].rows_duplicate += 1
    res.files = list(stats.values())


def _no_rows(table: str, keys: list[str]) -> dict[str, tuple]:
    return {}


def transform(files: dict[str, list[SourceFile]], open_records: dict[str, list[OpenRecord]] | None = None,
              db_keys: dict[str, set[str]] | None = None,
              existing: ExistingRows | None = None) -> dict[str, TableResult]:
    """files: new source files per table. open_records: rows in quarantine per table.
    db_keys: primary keys already loaded per table. existing: clean values of loaded keys."""
    open_records, db_keys, existing = open_records or {}, db_keys or {}, existing or _no_rows
    results: dict[str, TableResult] = {}
    for spec in SPECS:
        mine = files.get(spec.name, [])
        cands = _candidates(spec, open_records.get(spec.name, []), mine)
        res, passing = clean_table(spec, cands, db_keys.get(spec.name, set()), existing)
        apply_foreign_keys(spec, res, passing, results, db_keys)
        _file_stats(res, mine)
        results[spec.name] = res

    for res in results.values():
        for f in res.files:
            assert f.rows_loaded + f.rows_quarantined + f.rows_duplicate == f.rows_read, (res.spec.name, f.name)
        dropped = sum(1 for q in res.duplicates if q.quarantine_id is not None)
        assert len(res.graduated) + len(res.still_open) + dropped == res.rechecked, res.spec.name
        assert all(q.rule_id in RULES for q in res.quarantined + res.duplicates), res.spec.name
    return results


def transform_dir(raw_dir: pathlib.Path) -> dict[str, TableResult]:
    """Offline: treat every file under raw_dir as new, with an empty database."""
    files = {t: [read_source(t, name, p) for name, p in found] for t, found in discover(raw_dir).items()}
    return transform(files)
