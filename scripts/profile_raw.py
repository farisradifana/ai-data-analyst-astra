"""Phase 1 raw-data profiler for the Astra synthetic analytics project.

Read-only: never modifies files in raw-data/. Writes:
  reports/profiling/source_inventory.csv
  reports/profiling/profile_<table>.json
  reports/profiling/profiling_summary.md

Usage: python scripts/profile_raw.py [--raw-dir raw-data] [--out reports/profiling]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger("profile_raw")

SENTINELS = {"", "NULL", "NUL", "NONE", "N/A", "NA", "NAN", "-", "?", "UNKNOWN", "#N/A"}
DATE_PATTERNS = {
    "YYYY-MM-DD": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "YYYY/MM/DD": re.compile(r"^\d{4}/\d{2}/\d{2}$"),
    "DD/MM/YYYY": re.compile(r"^\d{2}/\d{2}/\d{4}$"),
    "MM-DD-YYYY": re.compile(r"^\d{2}-\d{2}-\d{4}$"),
    "D Mon YYYY": re.compile(r"^\d{1,2} [A-Za-z]{3,9} \d{4}$"),
}
NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")
MONEY_RE = re.compile(r"^(Rp\s?)?-?[\d,]+(\.\d+)?$", re.IGNORECASE)
ID_RE = re.compile(r"^[A-Z]{2,4}\d+$")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_dates(s: pd.Series) -> dict[str, int]:
    vals = s.dropna().str.strip()
    vals = vals[vals != ""]
    out: dict[str, int] = {}
    matched = pd.Series(False, index=vals.index)
    for name, pat in DATE_PATTERNS.items():
        m = vals.str.match(pat)
        if m.any():
            out[name] = int(m.sum())
        matched |= m
    if (~matched).any():
        out["UNRECOGNISED"] = int((~matched).sum())
        out["_unrecognised_examples"] = vals[~matched].unique()[:5].tolist()  # type: ignore[assignment]
    return out


def profile_column(name: str, s: pd.Series) -> dict:
    raw = s
    stripped = raw.str.strip()
    n = len(raw)
    info: dict = {
        "column": name,
        "null": int(raw.isna().sum()),
        "empty_or_whitespace": int((stripped == "").sum()),
        "sentinel": int(stripped.str.upper().isin(SENTINELS - {""}).sum()),
        "leading_trailing_ws": int(((raw != stripped) & raw.notna()).sum()),
        "distinct": int(raw.nunique(dropna=True)),
        "distinct_after_trim_upper": int(stripped.str.upper().nunique(dropna=True)),
    }
    nonnull = stripped.dropna()
    nonnull = nonnull[nonnull != ""]
    info["missing_pct"] = round(100 * (info["null"] + info["empty_or_whitespace"] + info["sentinel"]) / n, 3) if n else 0
    lname = name.lower()
    if "date" in lname:
        info["kind"] = "date"
        info["date_formats"] = classify_dates(raw)
    elif lname in {"check_in", "check_out"}:
        info["kind"] = "time"
        info["examples"] = nonnull.unique()[:8].tolist()
    elif any(k in lname for k in ("amount", "price", "cost", "salary")):
        info["kind"] = "money"
        info["with_rp_prefix"] = int(nonnull.str.upper().str.startswith("RP").sum())
        info["with_thousand_sep"] = int(nonnull.str.contains(",").sum())
        bad = nonnull[~nonnull.str.match(MONEY_RE)]
        info["non_parsable"] = int(len(bad))
        info["non_parsable_examples"] = bad.unique()[:8].tolist()
        num = pd.to_numeric(nonnull.str.replace(r"(?i)rp", "", regex=True).str.replace(",", "").str.strip(), errors="coerce")
        info["negative"] = int((num < 0).sum())
        info["zero"] = int((num == 0).sum())
        if num.notna().any():
            info["min"], info["max"], info["median"] = float(num.min()), float(num.max()), float(num.median())
            q1, q3 = num.quantile(0.25), num.quantile(0.75)
            iqr = q3 - q1
            info["iqr_outliers"] = int(((num < q1 - 3 * iqr) | (num > q3 + 3 * iqr)).sum())
    elif any(k in lname for k in ("quantity", "reorder", "pct")):
        info["kind"] = "numeric"
        bad = nonnull[~nonnull.str.match(NUMERIC_RE)]
        info["non_parsable"] = int(len(bad))
        info["non_parsable_examples"] = bad.unique()[:8].tolist()
        num = pd.to_numeric(nonnull, errors="coerce")
        info["negative"] = int((num < 0).sum())
        info["zero"] = int((num == 0).sum())
        if num.notna().any():
            info["min"], info["max"], info["median"] = float(num.min()), float(num.max()), float(num.median())
    elif lname.endswith("_id") or lname in {"warehouse_code"}:
        info["kind"] = "identifier"
        info["pattern_mismatch"] = int((~nonnull.str.match(ID_RE) & ~nonnull.str.match(r"^WH-[A-Z]{3}-\d{2}$")).sum())
        info["examples_mismatch"] = nonnull[~nonnull.str.match(ID_RE) & ~nonnull.str.match(r"^WH-[A-Z]{3}-\d{2}$")].unique()[:5].tolist()
    elif lname in {"phone"}:
        info["kind"] = "phone"
        info["leading_zero"] = int(nonnull.str.startswith("0").sum())
        info["patterns"] = nonnull.str.replace(r"\d", "9", regex=True).value_counts().head(8).to_dict()
    elif lname == "email":
        info["kind"] = "email"
        info["invalid_format"] = int((~nonnull.str.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")).sum())
    else:
        info["kind"] = "text"
    if info["kind"] in {"text"} and info["distinct_after_trim_upper"] <= 60:
        info["raw_values"] = raw.value_counts(dropna=False).head(60).to_dict()
        info["normalised_values"] = stripped.str.upper().value_counts(dropna=False).head(40).to_dict()
    return info


def profile_file(path: Path) -> tuple[dict, pd.DataFrame]:
    raw_bytes = path.read_bytes()[:4]
    bom = raw_bytes.startswith(b"\xef\xbb\xbf")
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[], encoding="utf-8-sig")
    # pandas keeps "" for blanks with keep_default_na=False; mark true NULL as NaN only if column missing
    cols = list(df.columns)
    pk = cols[0]
    prof = {
        "file": path.name,
        "table": path.stem,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "encoding": "utf-8-sig" if bom else "utf-8",
        "delimiter": ",",
        "rows": len(df),
        "columns": len(cols),
        "column_names": cols,
        "duplicate_column_names": [c for c in cols if cols.count(c) > 1],
        "suspicious_column_names": [c for c in cols if c != c.strip() or c.lower() != c or " " in c],
        "candidate_pk": pk,
        "exact_duplicate_rows": int(df.duplicated(keep=False).sum()),
        "exact_duplicate_extra_rows": int(df.duplicated().sum()),
        "pk_duplicate_rows": int(df[pk].str.strip().duplicated(keep=False).sum()),
        "pk_duplicate_keys": int(df[pk].str.strip().duplicated().sum()),
        "pk_duplicates_not_exact": 0,
        "column_profiles": [profile_column(c, df[c]) for c in cols],
    }
    dup_keys = df[df[pk].str.strip().duplicated(keep=False)]
    if len(dup_keys):
        prof["pk_duplicates_not_exact"] = int(len(dup_keys.drop_duplicates()) - dup_keys[pk].str.strip().nunique())
    return prof, df


FK_MAP = {
    "employee_id": "employees",
    "manager_id": "employees",
    "submitted_by_employee_id": "employees",
    "buyer_employee_id": "employees",
    "technician_employee_id": "employees",
    "customer_id": "customers",
    "product_id": "products",
    "supplier_id": "suppliers",
}


def fk_checks(frames: dict[str, pd.DataFrame]) -> list[dict]:
    keys = {t: set(df[df.columns[0]].str.strip()) for t, df in frames.items()}
    out = []
    for t, df in frames.items():
        for col in df.columns[1:]:
            parent = FK_MAP.get(col)
            if not parent or parent not in keys:
                continue
            vals = df[col].str.strip()
            present = vals[vals != ""]
            orphan = present[~present.isin(keys[parent])]
            out.append({
                "child": t, "column": col, "parent": parent,
                "non_blank": int(len(present)), "blank": int((vals == "").sum()),
                "orphans": int(len(orphan)), "orphan_examples": orphan.unique()[:5].tolist(),
            })
    return out


def write_summary(out: Path, profiles: list[dict], fks: list[dict]) -> None:
    lines = ["# Raw Data Profiling Summary (Phase 1)", "",
             f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}  ",
             "Source: `raw-data/` (read-only). All data is SYNTHETIC.", "",
             "## Source inventory", "",
             "| Table | Rows | Cols | Size (KB) | Exact dup extra rows | PK dup keys | SHA-256 (first 12) |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for p in profiles:
        lines.append(f"| {p['table']} | {p['rows']:,} | {p['columns']} | {p['bytes']//1024:,} | "
                     f"{p['exact_duplicate_extra_rows']:,} | {p['pk_duplicate_keys']:,} | `{p['sha256'][:12]}` |")
    lines.append(f"| **TOTAL** | **{sum(p['rows'] for p in profiles):,}** | | "
                 f"**{sum(p['bytes'] for p in profiles)//1024:,}** | "
                 f"**{sum(p['exact_duplicate_extra_rows'] for p in profiles):,}** | "
                 f"**{sum(p['pk_duplicate_keys'] for p in profiles):,}** | |")
    lines += ["", "## Referential integrity (orphan foreign keys)", "",
              "| Child.column | Parent | Non-blank | Blank | Orphans | Examples |", "|---|---|---:|---:|---:|---|"]
    for f in fks:
        lines.append(f"| {f['child']}.{f['column']} | {f['parent']} | {f['non_blank']:,} | {f['blank']:,} | "
                     f"{f['orphans']:,} | {', '.join(map(str, f['orphan_examples']))} |")
    lines += ["", "## Column issues per table", ""]
    for p in profiles:
        lines += [f"### {p['table']}", "",
                  "| Column | Kind | Missing % | Leading/trailing WS | Distinct raw / normalised | Notes |",
                  "|---|---|---:|---:|---|---|"]
        for c in p["column_profiles"]:
            notes = []
            if "date_formats" in c:
                notes.append("formats: " + ", ".join(f"{k}={v}" for k, v in c["date_formats"].items() if not k.startswith("_")))
                if "_unrecognised_examples" in c["date_formats"]:
                    notes.append("bad e.g. " + ", ".join(map(str, c["date_formats"]["_unrecognised_examples"])))
            for k in ("with_rp_prefix", "non_parsable", "negative", "zero", "iqr_outliers", "pattern_mismatch",
                      "invalid_format", "sentinel"):
                if c.get(k):
                    notes.append(f"{k}={c[k]:,}")
            if c.get("non_parsable_examples"):
                notes.append("e.g. " + ", ".join(map(str, c["non_parsable_examples"][:4])))
            if c.get("examples_mismatch"):
                notes.append("e.g. " + ", ".join(map(str, c["examples_mismatch"][:4])))
            if "normalised_values" in c:
                vals = [str(k) for k in c["normalised_values"]][:12]
                notes.append("values: " + ", ".join(vals))
            if "patterns" in c:
                notes.append("patterns: " + ", ".join(list(c["patterns"])[:4]))
            if "min" in c:
                notes.append(f"min={c['min']:,.0f} max={c['max']:,.0f}")
            lines.append(f"| {c['column']} | {c['kind']} | {c['missing_pct']} | {c['leading_trailing_ws']:,} | "
                         f"{c['distinct']:,} / {c['distinct_after_trim_upper']:,} | {'; '.join(notes).replace('|', '/')} |")
        lines.append("")
    (out / "profiling_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--raw-dir", type=Path, default=root / "raw-data")
    ap.add_argument("--out", type=Path, default=root / "reports" / "profiling")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    a.out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in a.raw_dir.iterdir() if p.suffix.lower() in {".csv", ".xlsx", ".xls", ".json"})
    if not files:
        log.error("no data files in %s", a.raw_dir)
        return 2
    profiles, frames, inv = [], {}, []
    for f in files:
        if f.suffix.lower() != ".csv":
            log.warning("unsupported in phase 1 profiler: %s", f.name)
            continue
        log.info("profiling %s", f.name)
        p, df = profile_file(f)
        profiles.append(p)
        frames[p["table"]] = df
        inv.append({k: p[k] for k in ("table", "file", "bytes", "rows", "columns", "encoding", "delimiter", "sha256",
                                       "candidate_pk", "exact_duplicate_extra_rows", "pk_duplicate_keys")})
        (a.out / f"profile_{p['table']}.json").write_text(json.dumps(p, indent=2, default=str), encoding="utf-8")
    fks = fk_checks(frames)
    (a.out / "fk_checks.json").write_text(json.dumps(fks, indent=2), encoding="utf-8")
    pd.DataFrame(inv).to_csv(a.out / "source_inventory.csv", index=False)
    write_summary(a.out, profiles, fks)
    log.info("done: %d files, %d rows", len(profiles), sum(p["rows"] for p in profiles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
