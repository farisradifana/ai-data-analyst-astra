r"""Telegram alerts for ETL runs. Counts only: no record content, keys, file names or personal data.

Config comes from .env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, optional TELEGRAM_MESSAGE_THREAD_ID.
If the token or chat id is empty, alerts are switched off (nothing is sent, nothing is guessed).
Thresholds are in config/alert_policy.json.

From the project folder, in PowerShell or cmd:
  .\astra notify check             check the config format (no network)
  .\astra notify check --online    also ask Telegram if the bot can see the chat (sends no message)
  .\astra notify preview           print the alerts the last run summary would send (no network)
  .\astra notify test              send one test message to the configured chat
  .\astra notify timeout --minutes N   JOB_TIMEOUT alert (sent by scripts\daily_etl.ps1)

Sending: plain text (no HTML/Markdown parsing), at most 4096 characters, at least 1.1 s between
messages and at most 18 per minute (Telegram's group limit is 20). Network errors, HTTP 429 and 5xx
are retried with exponential backoff (429 waits Telegram's retry_after); other errors are not.
The bot token is never printed or logged.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import Callable

from .db import ROOT, load_env

API = "https://api.telegram.org"
MAX_TEXT = 4096
TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")
CHAT_RE = re.compile(r"^(-?\d{5,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")
THREAD_RE = re.compile(r"^\d{1,10}$")
POLICY_FILE = ROOT / "config" / "alert_policy.json"
DEFAULT_POLICY = {"quarantine_new_rows_warn": 500, "quarantine_new_pct_warn": 5.0,
                  "stale_source_warn_on_scheduled": True, "top_rules": 3}

INFO, WARNING, CRITICAL = "INFO", "WARNING", "CRITICAL"


class NotifyError(RuntimeError):
    """A send that failed after retries, or was refused. The message never contains the token."""


@dataclasses.dataclass(frozen=True)
class TelegramConfig:
    token: str
    chat_id: str
    thread_id: int | None = None

    def __repr__(self) -> str:  # never show the token
        return f"TelegramConfig(chat_id=<set>, thread_id={'<set>' if self.thread_id else None})"


def config_from_env(env: dict[str, str]) -> TelegramConfig | None:
    """None when alerts are off (token or chat id empty). Raises ValueError on a malformed value."""
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    thread = (env.get("TELEGRAM_MESSAGE_THREAD_ID") or "").strip()
    if not token or not chat:
        return None
    if not TOKEN_RE.match(token):
        raise ValueError("TELEGRAM_BOT_TOKEN does not look like a bot token (digits:secret)")
    if not CHAT_RE.match(chat):
        raise ValueError("TELEGRAM_CHAT_ID must be a numeric chat id (groups start with -100) or @channelname")
    if thread and not THREAD_RE.match(thread):
        raise ValueError("TELEGRAM_MESSAGE_THREAD_ID must be a number or empty")
    return TelegramConfig(token, chat, int(thread) if thread else None)


def load_policy(path=POLICY_FILE) -> dict:
    policy = dict(DEFAULT_POLICY)
    if path.exists():
        policy.update(json.loads(path.read_text(encoding="utf-8")))
    return policy


# ---------------------------------------------------------------- transport

def _urllib_post(url: str, data: dict, timeout: float) -> tuple[int, dict]:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except ValueError:
            payload = {}
        return e.code, payload


class Telegram:
    """Bot API client with retry, backoff and a rate limit. `post` and `sleep` are injectable for tests."""

    def __init__(self, cfg: TelegramConfig, post: Callable = _urllib_post, sleep: Callable = time.sleep,
                 clock: Callable = time.monotonic, max_attempts: int = 4, timeout: float = 15.0,
                 min_interval: float = 1.1, per_minute: int = 18, max_wait: float = 60.0):
        self.cfg, self._post, self._sleep, self._clock = cfg, post, sleep, clock
        self.max_attempts, self.timeout, self.max_wait = max(1, min(max_attempts, 6)), timeout, max_wait
        self.min_interval, self.per_minute = min_interval, per_minute
        self._sent: deque[float] = deque()

    def _clean(self, text: str) -> str:
        return text.replace(self.cfg.token, "<token>")

    def _throttle(self) -> None:
        now = self._clock()
        while self._sent and now - self._sent[0] >= 60:
            self._sent.popleft()
        wait = 0.0
        if self._sent:
            wait = max(wait, self.min_interval - (now - self._sent[-1]))
        if len(self._sent) >= self.per_minute:
            wait = max(wait, 60 - (now - self._sent[0]))
        if wait > 0:
            self._sleep(wait)

    def call(self, method: str, data: dict) -> dict:
        url = f"{API}/bot{self.cfg.token}/{method}"
        last = "no attempt"
        for attempt in range(1, self.max_attempts + 1):
            if method == "sendMessage":
                self._throttle()
            try:
                status, payload = self._post(url, data, self.timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                status, payload, last = 0, {}, f"network error ({type(e).__name__})"
            if method == "sendMessage" and status:
                self._sent.append(self._clock())
            if status == 200 and payload.get("ok"):
                return payload.get("result") or {}
            if status:
                last = f"HTTP {status}: {self._clean(str(payload.get('description', '')))[:200]}"
            retryable = status == 0 or status == 429 or status >= 500
            if not retryable or attempt == self.max_attempts:
                break
            if status == 429:
                wait = float((payload.get("parameters") or {}).get("retry_after") or 1)
            else:
                wait = min(2 ** (attempt - 1), 30) + random.uniform(0, 0.5)
            self._sleep(min(wait, self.max_wait))
        raise NotifyError(f"Telegram {method} failed after {attempt} attempt(s): {last}")

    def send(self, text: str) -> int:
        data = {"chat_id": self.cfg.chat_id, "text": text[:MAX_TEXT], "disable_web_page_preview": "true"}
        if self.cfg.thread_id:
            data["message_thread_id"] = str(self.cfg.thread_id)
        return int(self.call("sendMessage", data).get("message_id") or 0)


# ---------------------------------------------------------------- alerts (counts only)

@dataclasses.dataclass(frozen=True)
class Alert:
    category: str   # ETL_SUCCESS | ETL_FAILED | QUARANTINE_SPIKE | STALE_SOURCE | TEST
    severity: str
    text: str


def _n(x: int) -> str:
    return f"{x:,}"


def run_alerts(summary: dict, trigger: str, seconds: float, policy: dict | None = None) -> list[Alert]:
    """Alerts for a finished load, from the counts-only run summary (reports/etl/last_run_summary.json)."""
    policy = policy or DEFAULT_POLICY
    tot, tables = summary["totals"], summary["tables"]
    run = (summary.get("run_id") or "dry-run")[:8]
    new_files = sum(len(t["new_files"]) for t in tables)
    rules: dict[str, int] = {}
    for t in tables:
        for k, v in t["rules_open_after"].items():
            rules[k] = rules.get(k, 0) + v
    top = sorted(rules.items(), key=lambda kv: (-kv[1], kv[0]))[: int(policy["top_rules"])]
    per_table = ", ".join(f"{t['table']} {len(t['new_files'])}" for t in tables if t["new_files"])
    lines = [f"[ASTRA ETL] OK - run {run} - {trigger} - SYNTHETIC data",
             f"New files: {new_files}" + (f" ({per_table})" if per_table else ""),
             f"Rows read {_n(tot['rows_read'])}, loaded {_n(tot['rows_loaded_new'])}, "
             f"quarantined {_n(tot['rows_quarantined_new'])}, duplicates {_n(tot['rows_duplicate_new'])}",
             f"Quarantine: rechecked {_n(tot['quarantine_rechecked'])}, graduated {_n(tot['quarantine_graduated'])}, "
             f"still to fix {_n(tot['quarantine_open_after'])}"]
    if top:
        lines.append("Top open rules: " + "; ".join(f"{k} {_n(v)}" for k, v in top))
    lines.append(f"Took {seconds:.1f} s. Details: reports/etl/last_run_summary.md")
    alerts = [Alert("ETL_SUCCESS", INFO, "\n".join(lines))]

    read, quarantined = tot["rows_read"], tot["rows_quarantined_new"]
    pct = 100.0 * quarantined / read if read else 0.0
    if quarantined and (quarantined >= policy["quarantine_new_rows_warn"] or pct >= policy["quarantine_new_pct_warn"]):
        worst = sorted(tables, key=lambda t: -t["rows_quarantined_new"])[:3]
        alerts.append(Alert("QUARANTINE_SPIKE", WARNING,
                            f"[ASTRA ETL] WARNING - run {run} - many new rows quarantined\n"
                            f"{_n(quarantined)} of {_n(read)} new rows ({pct:.1f}%)\n"
                            + "Most: " + "; ".join(f"{t['table']} {_n(t['rows_quarantined_new'])}"
                                                   for t in worst if t["rows_quarantined_new"])
                            + "\nCheck: .\\astra fix list"))
    if trigger == "SCHEDULED" and new_files == 0 and policy["stale_source_warn_on_scheduled"]:
        alerts.append(Alert("STALE_SOURCE", WARNING,
                            f"[ASTRA ETL] WARNING - run {run} - no new source files\n"
                            "The scheduled run found no new file in raw-data/<table>/."))
    return alerts


def failure_alert(stage: str, error: BaseException, trigger: str) -> Alert:
    """Only the stage and the exception type: error messages can quote row values."""
    return Alert("ETL_FAILED", CRITICAL,
                 f"[ASTRA ETL] FAILED - {trigger} - stage: {stage}\n"
                 f"Error type: {type(error).__name__}. Nothing was committed by the failed run.\n"
                 "See the console output or logs on the ETL machine.")


def timeout_alert(minutes: int) -> Alert:
    """Sent by scripts/daily_etl.ps1 when it stops a scheduled run that ran too long."""
    return Alert("JOB_TIMEOUT", CRITICAL,
                 f"[ASTRA ETL] FAILED - SCHEDULED - stopped after {int(minutes)} min (time limit)\n"
                 "The open transaction was rolled back, so nothing from this run was committed.\n"
                 "See logs\\etl on the ETL machine.")


def deliver(alerts: list[Alert], client: Telegram | None, log: Callable = print) -> int:
    """Sends each alert; never raises (alerting must not break the ETL). Returns the number sent."""
    if client is None:
        return 0
    sent = 0
    for a in alerts:
        try:
            client.send(a.text)
            sent += 1
        except NotifyError as e:
            log(f"alert {a.category} not sent: {e}")
    return sent


def client_from_env(log: Callable = print) -> Telegram | None:
    try:
        cfg = config_from_env(load_env())
    except (ValueError, RuntimeError) as e:
        log(f"Telegram alerts off: {e}")
        return None
    return Telegram(cfg) if cfg else None


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="astra notify")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("--online", action="store_true", help="getMe + getChat (sends no message)")
    sub.add_parser("preview")
    sub.add_parser("test")
    p = sub.add_parser("timeout", help="send a JOB_TIMEOUT alert (used by scripts/daily_etl.ps1)")
    p.add_argument("--minutes", type=int, required=True)
    a = ap.parse_args(argv)

    if a.cmd == "preview":
        path = ROOT / "reports" / "etl" / "last_run_summary.json"
        if not path.exists():
            print("no run summary yet: run .\\astra etl --dry-run first")
            return 2
        summary = json.loads(path.read_text(encoding="utf-8"))
        for al in run_alerts(summary, "MANUAL", 0.0, load_policy()):
            print(f"--- {al.category} ({al.severity})\n{al.text}")
        return 0

    try:
        cfg = config_from_env(load_env())
    except (ValueError, RuntimeError) as e:
        print(f"config error: {e}")
        return 2
    if cfg is None:
        print("Telegram alerts are off: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set in .env")
        return 2
    print(f"config ok: token format valid, chat id set, thread id {'set' if cfg.thread_id else 'not set'}")
    client = Telegram(cfg)
    try:
        if a.cmd == "check":
            if a.online:
                me = client.call("getMe", {})
                chat = client.call("getChat", {"chat_id": cfg.chat_id})
                print(f"bot ok (is_bot={me.get('is_bot')}); chat visible, type={chat.get('type')}"
                      + (f", topics={'on' if chat.get('is_forum') else 'off'}" if chat.get("type") == "supergroup" else ""))
            return 0
        if a.cmd == "timeout":
            client.send(timeout_alert(max(1, min(a.minutes, 1440))).text)
            print("timeout alert sent")
            return 0
        client.send("[ASTRA] Test alert - SYNTHETIC platform. If you can read this, ETL alerts reach this chat.")
        print("test message sent")
        return 0
    except NotifyError as e:
        print(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
