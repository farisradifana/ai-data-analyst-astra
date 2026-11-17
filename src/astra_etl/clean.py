"""Pure value cleaners. Each returns the canonical value or raises CleanError(issue_code).

Issue codes (shared with the Laya DQ labels):
  MISSING_REQUIRED_FIELD, INVALID_DATE_FORMAT, INVALID_NUMERIC_VALUE, INVALID_CATEGORY,
  BUSINESS_RULE_VIOLATION, ORPHAN_FOREIGN_KEY, DUPLICATE_PRIMARY_KEY
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation

SENTINELS = {"", "N/A", "NA", "NULL", "NONE", "-", "UNKNOWN", "TBD"}


class CleanError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _ws(v: str | None) -> str:
    return re.sub(r"\s+", " ", (v or "")).strip()


def is_blank(v: str | None) -> bool:
    return _ws(v).upper() in SENTINELS


def optional(v: str | None) -> str | None:
    """Trimmed text, or None for blanks and sentinels."""
    return None if is_blank(v) else _ws(v)


def required(v: str | None) -> str:
    s = optional(v)
    if s is None:
        raise CleanError("MISSING_REQUIRED_FIELD")
    return s


def code(v: str | None, allowed: frozenset[str] | set[str], *, nullable: bool = False) -> str | None:
    """Categorical value: trim, collapse spaces, UPPER, must be in the closed set."""
    if is_blank(v):
        if nullable:
            return None
        raise CleanError("MISSING_REQUIRED_FIELD")
    s = _ws(v).upper()
    if s not in allowed:
        raise CleanError("INVALID_CATEGORY")
    return s


def name(v: str | None, *, nullable: bool = False) -> str | None:
    """Person/company/product names: trim, collapse spaces, Title Case."""
    s = optional(v)
    if s is None:
        if nullable:
            return None
        raise CleanError("MISSING_REQUIRED_FIELD")
    return s.title()


def identifier(v: str | None, *, nullable: bool = False) -> str | None:
    s = optional(v)
    if s is None:
        if nullable:
            return None
        raise CleanError("MISSING_REQUIRED_FIELD")
    s = s.upper()
    if not re.fullmatch(r"[A-Z0-9-]{1,32}", s):
        raise CleanError("INVALID_CATEGORY")
    return s


# Decision D1: YYYY-MM-DD, YYYY/MM/DD, DD/MM/YYYY (slash = day first), MM-DD-YYYY (dash = month first).
_DATE_PATTERNS = (
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), ("y", "m", "d")),
    (re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"), ("y", "m", "d")),
    (re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})"), ("d", "m", "y")),
    (re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})"), ("m", "d", "y")),
)


def date(v: str | None) -> dt.date:
    if is_blank(v):
        raise CleanError("MISSING_REQUIRED_FIELD")
    s = _ws(v)
    for rx, order in _DATE_PATTERNS:
        m = rx.fullmatch(s)
        if m:
            parts = dict(zip(order, (int(g) for g in m.groups())))
            try:
                return dt.date(parts["y"], parts["m"], parts["d"])
            except ValueError:
                raise CleanError("INVALID_DATE_FORMAT") from None
    raise CleanError("INVALID_DATE_FORMAT")


def time(v: str | None) -> dt.time | None:
    """'08:00', '08.15', '8:30 AM', '5:00 PM' -> time; blank -> None."""
    if is_blank(v):
        return None
    s = _ws(v).upper()
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})(?:\s*(AM|PM))?", s)
    if not m:
        raise CleanError("INVALID_DATE_FORMAT")
    h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if ampm:
        if not 1 <= h <= 12:
            raise CleanError("INVALID_DATE_FORMAT")
        h = h % 12 + (12 if ampm == "PM" else 0)
    try:
        return dt.time(h, mi)
    except ValueError:
        raise CleanError("INVALID_DATE_FORMAT") from None


def _number(v: str | None) -> Decimal:
    if is_blank(v):
        raise CleanError("MISSING_REQUIRED_FIELD")
    s = _ws(v)
    s = re.sub(r"^RP\s*", "", s, flags=re.IGNORECASE).replace(",", "").replace(" ", "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        raise CleanError("INVALID_NUMERIC_VALUE")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise CleanError("INVALID_NUMERIC_VALUE") from None


def money(v: str | None) -> Decimal:
    """'Rp 38,914,556', '624,759,596.00', ' 123.00 ' -> Decimal(2dp). Negative -> D4."""
    d = _number(v)
    if d < 0:
        raise CleanError("BUSINESS_RULE_VIOLATION")
    return d.quantize(Decimal("0.01"))


def integer(v: str | None, *, min_value: int) -> int:
    """Whole number >= min_value. Words ('two') are not guessed (D3)."""
    d = _number(v)
    if d != d.to_integral_value():
        raise CleanError("INVALID_NUMERIC_VALUE")
    i = int(d)
    if i < min_value:
        raise CleanError("INVALID_NUMERIC_VALUE")
    return i


def percent(v: str | None) -> Decimal:
    """'10', '10%' -> Decimal('10.00'), must be 0..100."""
    s = _ws(v).rstrip("%")
    d = _number(s)
    if not Decimal(0) <= d <= Decimal(100):
        raise CleanError("INVALID_NUMERIC_VALUE")
    return d.quantize(Decimal("0.01"))


def flag(v: str | None) -> bool:
    s = _ws(v).upper()
    if s in {"Y", "YES", "1", "TRUE"}:
        return True
    if s in {"N", "NO", "0", "FALSE"}:
        return False
    if s == "":
        raise CleanError("MISSING_REQUIRED_FIELD")
    raise CleanError("INVALID_CATEGORY")


# Decision D2.
_PAYMENT_TERMS = {"COD": "COD", "NET30": "NET30", "NET 30": "NET30", "30 DAYS": "NET30"}


def payment_terms(v: str | None) -> str:
    if is_blank(v):
        raise CleanError("MISSING_REQUIRED_FIELD")
    s = _ws(v).upper()
    if s not in _PAYMENT_TERMS:
        raise CleanError("INVALID_CATEGORY")
    return _PAYMENT_TERMS[s]


def email(v: str | None) -> str | None:
    """Lower-cased email, or None for blanks/sentinels/invalid format (PII is optional)."""
    s = optional(v)
    if s is None:
        return None
    s = s.lower()
    return s if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", s) else None


def phone(v: str | None) -> str | None:
    """Digits/+/-/spaces kept as given; all-9 placeholders and sentinels -> None."""
    s = optional(v)
    if s is None:
        return None
    digits = re.sub(r"\D", "", s)
    if not digits or set(digits) == {"9"} or not re.fullmatch(r"\+?[\d\s-]{6,32}", s):
        return None
    return s
