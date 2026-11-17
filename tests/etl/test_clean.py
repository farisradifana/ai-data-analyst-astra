"""Cleaner rules (decisions D1-D6). Pure Python, no database."""
import datetime as dt
from decimal import Decimal

import pytest

from astra_etl import clean as c
from astra_etl.clean import CleanError


@pytest.mark.parametrize("raw,expected", [
    ("2026-09-17", dt.date(2026, 9, 17)),
    ("2025/06/22", dt.date(2025, 6, 22)),
    ("08/07/2024", dt.date(2024, 7, 8)),    # slash = day first (D1)
    ("08-21-2026", dt.date(2026, 8, 21)),   # dash = month first (D1)
    (" 2026-01-05 ", dt.date(2026, 1, 5)),
])
def test_date_formats(raw, expected):
    assert c.date(raw) == expected


@pytest.mark.parametrize("raw,code", [
    ("31/02/2024", "INVALID_DATE_FORMAT"),
    ("21-08-2026", "INVALID_DATE_FORMAT"),  # month 21 under the dash rule
    ("yesterday", "INVALID_DATE_FORMAT"),
    ("", "MISSING_REQUIRED_FIELD"),
    ("N/A", "MISSING_REQUIRED_FIELD"),
])
def test_date_rejects(raw, code):
    with pytest.raises(CleanError) as e:
        c.date(raw)
    assert e.value.code == code


@pytest.mark.parametrize("raw,expected", [
    ("Rp 38,914,556", Decimal("38914556.00")),
    ("624,759,596.00", Decimal("624759596.00")),
    (" 123177940.00 ", Decimal("123177940.00")),
    ("rp1,000", Decimal("1000.00")),
])
def test_money(raw, expected):
    assert c.money(raw) == expected


@pytest.mark.parametrize("raw,code", [
    ("-50000", "BUSINESS_RULE_VIOLATION"),  # D4
    ("unknown", "MISSING_REQUIRED_FIELD"),
    ("TBD", "MISSING_REQUIRED_FIELD"),
    ("12abc", "INVALID_NUMERIC_VALUE"),
])
def test_money_rejects(raw, code):
    with pytest.raises(CleanError) as e:
        c.money(raw)
    assert e.value.code == code


@pytest.mark.parametrize("raw", ["0", "-1", "two", "1.5"])
def test_sales_quantity_rejects(raw):  # D3: no word-to-number guessing
    with pytest.raises(CleanError) as e:
        c.integer(raw, min_value=1)
    assert e.value.code == "INVALID_NUMERIC_VALUE"


def test_integer_ok():
    assert c.integer(" 3 ", min_value=1) == 3


@pytest.mark.parametrize("raw,expected", [("10%", Decimal("10.00")), ("0", Decimal("0.00")), ("15", Decimal("15.00"))])
def test_percent(raw, expected):
    assert c.percent(raw) == expected


def test_percent_out_of_range():
    with pytest.raises(CleanError):
        c.percent("150%")


@pytest.mark.parametrize("raw,expected", [
    ("8:30 AM", dt.time(8, 30)), ("5:00 PM", dt.time(17, 0)), ("08.15", dt.time(8, 15)),
    ("17:30", dt.time(17, 30)), ("12:00 AM", dt.time(0, 0)), ("", None),
])
def test_time(raw, expected):
    assert c.time(raw) == expected


@pytest.mark.parametrize("raw,expected", [("Y", True), ("YES", True), ("1", True), ("N", False), ("0", False)])
def test_flag(raw, expected):
    assert c.flag(raw) is expected


@pytest.mark.parametrize("raw", ["NET30", "NET 30", "30 days", " net30 "])
def test_payment_terms_d2(raw):
    assert c.payment_terms(raw) == "NET30"


def test_code_normalises_and_checks_set():
    assert c.code("  on   leave ", {"ON LEAVE"}) == "ON LEAVE"
    with pytest.raises(CleanError) as e:
        c.code("FIRED", {"ACTIVE"})
    assert e.value.code == "INVALID_CATEGORY"


def test_pii_sentinels_become_null():
    assert c.email("N/A") is None and c.email("null") is None and c.email("not-an-email") is None
    assert c.email(" A@B.co ") == "a@b.co"
    assert c.phone("99999999999") is None and c.phone("null") is None
    assert c.phone("08550319015") == "08550319015"


def test_name_title_case():
    assert c.name("  INDRA   PERMATA ") == "Indra Permata"
