"""Benchmark Laya checkpoints on the labeled synthetic evaluation sets.

Usage (from project root, inside .venv-laya):
  python -m decision_engine.evaluation --checkpoints multilingual english typed-decisions

Writes reports/laya/eval_<checkpoint>_<task>.jsonl, reports/laya/benchmark.json and
reports/laya/benchmark.md. Does not change config/laya_policy.json; thresholds are proposed only.
"""
from __future__ import annotations

import argparse
import ctypes
import gc
import json
import logging
import platform
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import fallback
from .laya_engine import laya_choice
from .model_manager import ModelManager

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "evals" / "laya"
OUT = ROOT / "reports" / "laya"
TASK_FILES = {"dq_category": "dq_incidents.jsonl", "agent_route": "agent_routing.jsonl"}
log = logging.getLogger("decision_engine.evaluation")


def rss_mb() -> tuple[float, float]:
    """Current and peak working set (Windows). Returns (-1, -1) elsewhere."""
    if sys.platform != "win32":
        return -1.0, -1.0

    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t)] + \
                   [(f"f{i}", ctypes.c_size_t) for i in range(6)]

    c = PMC()
    c.cb = ctypes.sizeof(c)
    k32 = ctypes.windll.kernel32
    k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
    if not k32.K32GetProcessMemoryInfo(ctypes.c_void_p(-1), ctypes.byref(c), c.cb):
        return -1.0, -1.0
    return c.WorkingSetSize / 2**20, c.PeakWorkingSetSize / 2**20


def load_set(task: str) -> list[dict]:
    lines = (EVAL_DIR / TASK_FILES[task]).read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines if x.strip()]


def metrics(rows: list[dict], labels: list[str]) -> dict:
    n = len(rows)
    correct = sum(r["correct"] for r in rows)
    per = {}
    for lab in labels:
        tp = sum(1 for r in rows if r["pred"] == lab and r["label"] == lab)
        fp = sum(1 for r in rows if r["pred"] == lab and r["label"] != lab)
        fn = sum(1 for r in rows if r["pred"] != lab and r["label"] == lab)
        p = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        per[lab] = {"precision": round(p, 3), "recall": round(rc, 3),
                    "f1": round(2 * p * rc / (p + rc), 3) if p + rc else 0.0, "support": tp + fn}
    by_lang = defaultdict(list)
    for r in rows:
        by_lang[r["lang"]].append(r["correct"])
    # 5-bin expected calibration error on reported confidence
    bins = defaultdict(list)
    for r in rows:
        bins[min(int(r["conf"] * 5), 4)].append(r)
    ece = sum(len(b) / n * abs(sum(x["correct"] for x in b) / len(b) - sum(x["conf"] for x in b) / len(b))
              for b in bins.values()) if n else 0.0
    conf_corr = [r["conf"] for r in rows if r["correct"]]
    conf_wrong = [r["conf"] for r in rows if not r["correct"]]
    return {
        "n": n,
        "accuracy": round(correct / n, 3) if n else 0.0,
        "macro_f1": round(sum(v["f1"] for v in per.values()) / len(per), 3),
        "accuracy_by_lang": {k: round(sum(v) / len(v), 3) for k, v in by_lang.items()},
        "ece_5bin": round(ece, 3),
        "mean_conf_correct": round(sum(conf_corr) / len(conf_corr), 3) if conf_corr else None,
        "mean_conf_wrong": round(sum(conf_wrong) / len(conf_wrong), 3) if conf_wrong else None,
        "per_label": per,
        "confusion": {f"{a}->{b}": c for (a, b), c in Counter((r["label"], r["pred"]) for r in rows).items() if a != b},
    }


def accuracy_at_thresholds(rows: list[dict]) -> list[dict]:
    out = []
    for t in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        kept = [r for r in rows if r["conf"] >= t]
        out.append({"threshold": t, "coverage": round(len(kept) / len(rows), 3),
                    "accuracy": round(sum(r["correct"] for r in kept) / len(kept), 3) if kept else None})
    return out


def run(checkpoints: list[str], threads: int) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hardware": {"cpu": platform.processor(), "machine": platform.machine(), "threads": threads,
                     "os": platform.platform()},
        "note": "Small synthetic labeled set; results are indicative only, not production accuracy.",
        "results": {},
    }
    # Deterministic fallback baseline for comparison.
    for task in TASK_FILES:
        data = load_set(task)
        labels = list(dict.fromkeys(r["label"] for r in data))
        rows = [{**r, "pred": fallback.classify(task, r["text"]), "conf": 1.0} for r in data]
        for r in rows:
            r["correct"] = r["pred"] == r["label"]
        report["results"].setdefault("rule_fallback", {})[task] = metrics(rows, labels)
    for ckpt in checkpoints:
        mm = ModelManager(ckpt, threads=threads)
        info = mm.info()
        t0 = time.perf_counter()
        try:
            mm.router()
            laya_choice(mm, "agent_route", "warm up")  # forces checkpoint load
        except Exception as exc:
            log.error("checkpoint %s failed to load: %s", ckpt, exc)
            report["results"][ckpt] = {"error": f"{type(exc).__name__}: {exc}"[:300], "model_info": info}
            continue
        load_s = time.perf_counter() - t0
        res: dict = {"model_info": info, "load_seconds": round(load_s, 1)}
        for task in TASK_FILES:
            data = load_set(task)
            labels = list(dict.fromkeys(r["label"] for r in data))
            rows, lat = [], []
            for r in data:
                s = time.perf_counter()
                pred, conf = laya_choice(mm, task, r["text"])
                lat.append((time.perf_counter() - s) * 1000)
                rows.append({**r, "pred": pred, "conf": round(conf, 4), "correct": pred == r["label"],
                             "checkpoint": ckpt, "revision": info["pinned_revision"]})
            with (OUT / f"eval_{ckpt}_{task}.jsonl").open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            lat.sort()
            m = metrics(rows, labels)
            m["latency_ms"] = {"p50": round(lat[len(lat) // 2], 1), "p95": round(lat[int(len(lat) * 0.95) - 1], 1),
                               "max": round(lat[-1], 1)}
            m["accuracy_at_threshold"] = accuracy_at_thresholds(rows)
            res[task] = m
        cur, peak = rss_mb()
        res["rss_mb_after"], res["peak_rss_mb"] = round(cur), round(peak)
        report["results"][ckpt] = res
        log.info("checkpoint %s done: %s", ckpt, {t: res[t]["accuracy"] for t in TASK_FILES})
        del mm
        gc.collect()
    (OUT / "benchmark.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_md(report)
    return report


def write_md(rep: dict) -> None:
    lines = ["# Laya benchmark (synthetic labeled set)", "", f"Generated: {rep['generated']}  ",
             f"Hardware: {rep['hardware']['cpu']} · threads={rep['hardware']['threads']} · CPU only  ",
             f"{rep['note']}", "",
             "| Model | Task | Acc | Acc EN | Acc ID | Macro F1 | ECE | Conf ok / wrong | p50 ms | p95 ms | Peak RSS MB |",
             "|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|"]
    for model, res in rep["results"].items():
        if "error" in res:
            lines.append(f"| {model} | — | load failed: {res['error']} | | | | | | | | |")
            continue
        for task in TASK_FILES:
            m = res[task]
            lat = m.get("latency_ms", {})
            lines.append(
                f"| {model} | {task} | {m['accuracy']} | {m['accuracy_by_lang'].get('en')} | "
                f"{m['accuracy_by_lang'].get('id')} | {m['macro_f1']} | "
                f"{m['ece_5bin'] if model != 'rule_fallback' else '—'} | "
                f"{m['mean_conf_correct']} / {m['mean_conf_wrong']} | {lat.get('p50', '—')} | {lat.get('p95', '—')} | "
                f"{res.get('peak_rss_mb', '—')} |")
    (OUT / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoints", nargs="+", default=["multilingual", "english", "typed-decisions"])
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run(a.checkpoints, a.threads)
    return 0


if __name__ == "__main__":
    sys.exit(main())
