"""Telegram alerts: config, retry/backoff, rate limit, counts-only content. No network."""
import urllib.error

import pytest

from astra_etl import __main__ as etl_main
from astra_etl import notify
from astra_etl.notify import (Telegram, TelegramConfig, NotifyError, config_from_env, deliver, failure_alert,
                              run_alerts)

TOKEN = "123456:" + "A1b2C3d4" * 5          # fake, format only
CHAT = "-100123"


class FakeApi:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, data, timeout):
        self.calls.append((url, dict(data)))
        r = self.responses.pop(0) if self.responses else (200, {"ok": True, "result": {"message_id": 1}})
        if isinstance(r, Exception):
            raise r
        return r


class Clock:
    def __init__(self):
        self.t, self.sleeps = 1000.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def _client(api, clock=None, **kw):
    clock = clock or Clock()
    return Telegram(TelegramConfig(TOKEN, CHAT, kw.pop("thread", None)), post=api, sleep=clock.sleep,
                    clock=clock, **kw), clock


def test_config_off_when_empty_and_strict_when_set():
    assert config_from_env({}) is None
    assert config_from_env({"TELEGRAM_BOT_TOKEN": TOKEN}) is None
    cfg = config_from_env({"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT, "TELEGRAM_MESSAGE_THREAD_ID": "7"})
    assert (cfg.chat_id, cfg.thread_id) == (CHAT, 7)
    assert TOKEN not in repr(cfg)
    for bad in ({"TELEGRAM_BOT_TOKEN": "abc", "TELEGRAM_CHAT_ID": CHAT},
                {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "my group"},
                {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT, "TELEGRAM_MESSAGE_THREAD_ID": "x"}):
        with pytest.raises(ValueError) as e:
            config_from_env(bad)
        assert TOKEN not in str(e.value)


def test_send_plain_text_to_thread_and_truncates():
    api = FakeApi()
    c, _ = _client(api, thread=42)
    c.send("x" * 5000)
    url, data = api.calls[0]
    assert url.endswith("/sendMessage")
    assert data["chat_id"] == CHAT and data["message_thread_id"] == "42"
    assert len(data["text"]) == 4096 and "parse_mode" not in data


def test_retries_5xx_and_network_then_succeeds():
    api = FakeApi((502, {"ok": False}), urllib.error.URLError("down"), (200, {"ok": True, "result": {"message_id": 9}}))
    c, clock = _client(api)
    assert c.send("hi") == 9
    assert len(api.calls) == 3
    assert sum(clock.sleeps) >= 1 + 2                              # backoff 1 s, then 2 s (plus spacing)


def test_429_waits_retry_after():
    api = FakeApi((429, {"ok": False, "parameters": {"retry_after": 7}}))
    c, clock = _client(api)
    c.send("hi")
    assert 7 in clock.sleeps


def test_no_retry_on_400_and_token_never_in_error():
    api = FakeApi((400, {"ok": False, "description": f"bad request for {TOKEN}"}))
    c, _ = _client(api)
    with pytest.raises(NotifyError) as e:
        c.send("hi")
    assert len(api.calls) == 1
    assert TOKEN not in str(e.value) and "HTTP 400" in str(e.value)


def test_gives_up_after_max_attempts():
    api = FakeApi(*[(500, {"ok": False})] * 10)
    c, _ = _client(api, max_attempts=3)
    with pytest.raises(NotifyError):
        c.send("hi")
    assert len(api.calls) == 3


def test_rate_limit_spacing_and_per_minute_cap():
    api = FakeApi()
    c, clock = _client(api, min_interval=1.1, per_minute=3)
    for _ in range(4):
        c.send("hi")
    assert clock.sleeps[0] == pytest.approx(1.1)
    assert sum(clock.sleeps) >= 60 - 1e-6           # 4th message waits for the minute window


def _summary(**tot):
    totals = {"rows_read": 1000, "rows_loaded_new": 990, "rows_quarantined_new": 8, "rows_duplicate_new": 2,
              "quarantine_rechecked": 5914, "quarantine_graduated": 80, "quarantine_open_after": 5842}
    totals.update(tot)
    tables = [{"table": "sales_transactions", "new_files": ["sales_transactions/2026-11-19-secret-name.csv"],
               "rows_quarantined_new": totals["rows_quarantined_new"],
               "rules_open_after": {"ORPHAN_PARENT_QUARANTINED": 4000, "NEGATIVE_AMOUNT": 79}},
              {"table": "products", "new_files": [], "rows_quarantined_new": 0,
               "rules_open_after": {"NEGATIVE_AMOUNT": 31}}]
    return {"run_id": "54f90cd1-aaaa-bbbb", "totals": totals, "tables": tables}


def test_run_alert_has_counts_only():
    (a,) = run_alerts(_summary(), "MANUAL", 6.2)
    assert a.category == "ETL_SUCCESS"
    assert "run 54f90cd1 " in a.text and "SYNTHETIC" in a.text
    assert "loaded 990" in a.text and "graduated 80" in a.text and "NEGATIVE_AMOUNT 110" in a.text
    assert "secret-name" not in a.text and ".csv" not in a.text   # file names are not sent
    assert "sales_transactions 1" in a.text


def test_spike_and_stale_alerts():
    cats = [a.category for a in run_alerts(_summary(rows_quarantined_new=600), "MANUAL", 1)]
    assert cats == ["ETL_SUCCESS", "QUARANTINE_SPIKE"]
    pct = [a.category for a in run_alerts(_summary(rows_quarantined_new=60), "MANUAL", 1)]
    assert "QUARANTINE_SPIKE" in pct                               # 6% of new rows
    s = _summary(rows_read=0, rows_quarantined_new=0)
    s["tables"][0]["new_files"] = []
    assert [a.category for a in run_alerts(s, "SCHEDULED", 1)] == ["ETL_SUCCESS", "STALE_SOURCE"]
    assert [a.category for a in run_alerts(s, "MANUAL", 1)] == ["ETL_SUCCESS"]


def test_failure_alert_hides_error_message():
    a = failure_alert("load", RuntimeError("Key (customer_id)=(CUS000123) budi@example.com"), "SCHEDULED")
    assert a.severity == "CRITICAL" and "stage: load" in a.text and "RuntimeError" in a.text
    assert "CUS000123" not in a.text and "example.com" not in a.text


def test_deliver_never_raises():
    api = FakeApi(*[(403, {"ok": False, "description": "bot was kicked"})] * 2)
    c, _ = _client(api)
    logged = []
    assert deliver(run_alerts(_summary(), "MANUAL", 1), c, log=logged.append) == 0
    assert deliver([], None) == 0
    assert logged and TOKEN not in logged[0]


def test_failed_load_sends_failure_alert_and_reraises(monkeypatch):
    sent = []

    class Fake:
        def send(self, text):
            sent.append(text)

    def boom(args, t0, stage):
        stage.name = "load"
        raise ValueError("row CUS000001 broke")

    monkeypatch.setattr(etl_main, "_run", boom)
    monkeypatch.setattr(notify, "client_from_env", lambda log=print: Fake())
    with pytest.raises(ValueError):
        etl_main.main(["etl"])
    assert len(sent) == 1 and "stage: load" in sent[0] and "CUS000001" not in sent[0]

    sent.clear()
    with pytest.raises(ValueError):
        etl_main.main(["etl", "--dry-run"])                        # dry runs never alert
    with pytest.raises(ValueError):
        etl_main.main(["etl", "--no-notify"])
    assert not sent
