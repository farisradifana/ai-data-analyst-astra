"""Deterministic keyword fallback used when Laya is unavailable or not confident.

Rules are simple and auditable. They return UNKNOWN/UNKNOWN_ERROR rather than guess.
"""
from __future__ import annotations

import re

_DQ_RULES: list[tuple[str, str]] = [
    (r"\b(cast|casting|convert|konversi|mengubah tipe|overflow)", "TYPE_CONVERSION_ERROR"),
    (r"\b(does not exist|not found|tidak ada|tidak ditemukan)\b.*\b(table|master|tabel)\b|\borphan\b", "ORPHAN_FOREIGN_KEY"),
    (r"\b(duplicate|twice|two times|ganda|dua kali|identik|identical)\b", "DUPLICATE_RECORD"),
    (r"\b(empty|blank|missing|kosong|tidak terisi|tidak memiliki)\b", "MISSING_REQUIRED_FIELD"),
    (r"\b(date|tanggal)\b.*\b(not a real|cannot be parsed|tidak valid|tidak dikenali|bukan tanggal)", "INVALID_DATE"),
    (r"\b(status)\b.*\b(not one of|not defined|tidak termasuk|tidak terdaftar|allowed|diizinkan)", "INVALID_BUSINESS_STATUS"),
    (r"\b(instead of a number|as a number|bukan angka|sebagai bilangan|non-numeric)", "INVALID_NUMERIC_VALUE"),
    (r"\b(spelling|spelled|written as|ditulis|tertulis|berbeda-beda)\b", "INCONSISTENT_CATEGORY"),
    (r"\b(negative|negatif|must be positive|earlier than|lebih awal|tidak boleh)\b", "BUSINESS_RULE_VIOLATION"),
]

_ROUTE_RULES: list[tuple[str, str]] = [
    (r"\b(rerun|reprocess|reload|proses ulang|jalankan ulang|re-run)\b", "REPROCESSING_REQUEST"),
    (r"\b(rejected|ditolak|quarantin\w*|validation|validasi|tidak masuk)\b", "DATA_QUALITY"),
    (r"\b(pipeline|refresh|di-refresh|last successful load|etl)\b", "PIPELINE_STATUS"),
    (r"\b(connect|konek|menghubungkan|error|timeout|ssl|navicat|reset)\b", "TECHNICAL_SUPPORT"),
    (r"\b(why|kenapa|mengapa|compare|banding|trend|analy[sz]e|performa|recommend)\w*", "BUSINESS_ANALYSIS"),
    (r"\b(berapa|how many|how much|total|jumlah|what is the total)\b", "KPI_QUERY"),
    (r"\b(halo|hello|hi|apa itu|what does|what can you do|bisa bantu)\b", "GENERAL_QUESTION"),
]


def _match(text: str, rules: list[tuple[str, str]], default: str) -> str:
    t = text.lower()
    for pattern, label in rules:
        if re.search(pattern, t):
            return label
    return default


def classify_dq(text: str) -> str:
    return _match(text, _DQ_RULES, "UNKNOWN_ERROR")


def classify_route(text: str) -> str:
    return _match(text, _ROUTE_RULES, "UNKNOWN")


def classify(task: str, text: str) -> str:
    if task == "dq_category":
        return classify_dq(text)
    if task == "agent_route":
        return classify_route(text)
    raise ValueError(f"unknown task: {task}")
