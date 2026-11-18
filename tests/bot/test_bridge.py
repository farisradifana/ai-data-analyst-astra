"""Telegram bridge: allow-list, chat rules, loopback-only webhook, bounded polling (spec case 16)."""
import json
import urllib.error

import pytest

from astra_bot import bridge as b
from astra_etl.notify import NotifyError

TOKEN = "123456789:" + "A" * 35
WTOKEN = "w" * 40
ALLOWED, STRANGER, GROUP = 1111, 2222, -55555   # fake ids


def env(**over):
    e = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_ALLOWED_USER_IDS": str(ALLOWED), "TELEGRAM_CHAT_ID": str(GROUP),
         "ASTRA_ASSISTANT_WEBHOOK_TOKEN": WTOKEN}
    e.update(over)
    return e


class FakeTG:
    def __init__(self, responses=None):
        self.calls, self.responses = [], responses or {}

    def call(self, method, data):
        self.calls.append((method, data))
        r = self.responses.get(method)
        if isinstance(r, list):
            r = r.pop(0) if r else []
        if isinstance(r, Exception):
            raise r
        return {} if r is None else r

    def sent(self):
        return [d for m, d in self.calls if m == "sendMessage"]


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def make(ask=None, tg=None, clock=None, logs=None):
    cfg = b.config_from_env(env())
    asked = []

    def default_ask(q, s):
        asked.append((q, s))
        return "Net revenue 2025: Rp 54.269.362.661.171"

    br = b.Bridge(cfg, tg or FakeTG(), ask or default_ask, clock=clock or Clock(),
                  log=(logs.append if logs is not None else (lambda _l: None)), bot_username="astra_bot")
    return br, asked


def msg(text, uid=ALLOWED, chat_type="private", chat_id=None, date=None, **extra):
    chat_id = chat_id if chat_id is not None else (uid if chat_type == "private" else GROUP)
    m = {"message_id": 7, "date": date if date is not None else 1_000_000, "text": text,
         "from": {"id": uid}, "chat": {"id": chat_id, "type": chat_type}}
    m.update(extra)
    return {"update_id": 1, "message": m}


# ---------------------------------------------------------------- config

def test_config_defaults_to_loopback_webhook_and_hides_secrets():
    cfg = b.config_from_env(env())
    assert cfg.webhook_url == b.DEFAULT_WEBHOOK_URL
    assert cfg.allowed_users == {ALLOWED} and cfg.group_chat_id == GROUP
    assert TOKEN not in repr(cfg) and WTOKEN not in repr(cfg) and str(ALLOWED) not in repr(cfg)


@pytest.mark.parametrize("over, text", [
    ({"TELEGRAM_ALLOWED_USER_IDS": ""}, "empty"),
    ({"TELEGRAM_ALLOWED_USER_IDS": "12,abc"}, "numeric"),
    ({"TELEGRAM_BOT_TOKEN": "nope"}, "bot token"),
    ({"ASTRA_ASSISTANT_WEBHOOK_TOKEN": "short"}, "32"),
    ({"ASTRA_ASSISTANT_WEBHOOK_URL": "https://example.com/webhook/astra-assistant"}, "127.0.0.1"),
    ({"ASTRA_ASSISTANT_WEBHOOK_URL": "http://127.0.0.1.evil.example/webhook"}, "127.0.0.1"),
    ({"ASTRA_ASSISTANT_WEBHOOK_URL": "http://10.0.0.5:5698/webhook/x"}, "127.0.0.1"),
    ({"ASTRA_ASSISTANT_WEBHOOK_URL": "http://u:p@127.0.0.1:5698/webhook/x"}, "credentials"),
    ({"ASTRA_ASSISTANT_WEBHOOK_URL": "file:///etc/passwd"}, "127.0.0.1"),
    ({"TELEGRAM_CHAT_ID": "@group"}, "numeric chat id"),
])
def test_config_rejects_unsafe_or_missing_values(over, text):
    with pytest.raises(b.BridgeConfigError, match=text) as e:
        b.config_from_env(env(**over))
    assert TOKEN not in str(e.value) and WTOKEN not in str(e.value)


def test_config_prefers_a_dedicated_assistant_bot_token():
    other = "987654321:" + "B" * 35
    assert b.config_from_env(env(TELEGRAM_ASSISTANT_BOT_TOKEN=other)).token == other
    assert b.config_from_env(env(TELEGRAM_ASSISTANT_BOT_TOKEN="")).token == TOKEN
    with pytest.raises(b.BridgeConfigError, match="TELEGRAM_ASSISTANT_BOT_TOKEN"):
        b.config_from_env(env(TELEGRAM_ASSISTANT_BOT_TOKEN="bad"))


def test_config_accepts_loopback_ip_literals_only():
    for url in ("http://[::1]:5698/webhook/a", "http://127.0.0.1:5698/webhook/a"):
        assert b.config_from_env(env(ASTRA_ASSISTANT_WEBHOOK_URL=url)).webhook_url == url
    for url in ("http://localhost:5698/webhook/a", "http://astra.localhost:5698/webhook/a"):
        with pytest.raises(b.BridgeConfigError, match="loopback IP"):
            b.config_from_env(env(ASTRA_ASSISTANT_WEBHOOK_URL=url))


def test_run_survives_a_malformed_telegram_response():
    tg = FakeTG({"getUpdates": ValueError("Expecting value")})
    logs = []
    br, _ = make(tg=tg, logs=logs)
    assert br.run(60, sleep=lambda s: None) == 1
    assert any("ValueError" in line for line in logs) and not any("Expecting" in line for line in logs)


def test_refusal_table_stays_bounded():
    clock = Clock()
    br, _ = make(clock=clock)
    for uid in range(5000, 5000 + b.MAX_TRACKED_USERS + 50):
        clock.t += b.REFUSAL_INTERVAL
        br.handle(msg("q", uid=uid))
    assert len(br._refused) <= b.MAX_TRACKED_USERS


# ---------------------------------------------------------------- authorization (spec case 16)

def test_unauthorized_user_is_refused_without_calling_the_assistant():
    logs = []
    br, asked = make(logs=logs)
    assert br.handle(msg("Berapa net revenue 2025?", uid=STRANGER)) == "refused"
    assert asked == []
    assert [d["text"] for d in br.tg.sent()] == [b.NOT_ALLOWED]
    assert any(str(STRANGER) in line for line in logs)          # owner can find the id locally


def test_refusal_reply_is_rate_limited():
    clock = Clock()
    br, _ = make(clock=clock)
    br.handle(msg("q1", uid=STRANGER))
    br.handle(msg("q2", uid=STRANGER))
    assert len(br.tg.sent()) == 1
    clock.t += b.REFUSAL_INTERVAL
    br.handle(msg("q3", uid=STRANGER))
    assert len(br.tg.sent()) == 2


def test_unauthorized_user_in_the_group_is_refused_too():
    br, asked = make()
    assert br.handle(msg("/ask hapus data", uid=STRANGER, chat_type="supergroup")) == "refused"
    assert asked == []


# ---------------------------------------------------------------- questions

def test_allowed_private_question_is_forwarded_and_answered():
    logs = []
    br, asked = make(logs=logs)
    assert br.handle(msg("Berapa net revenue 2025?")) == "answered"
    assert asked == [("Berapa net revenue 2025?", f"tg-{ALLOWED}-{ALLOWED}")]
    reply = br.tg.sent()[-1]
    assert reply["text"].startswith("Net revenue 2025") and reply["reply_to_message_id"] == "7"
    assert ("sendChatAction", {"chat_id": str(ALLOWED), "action": "typing"}) in br.tg.calls
    joined = "\n".join(logs)
    assert "Berapa" not in joined and "54.269" not in joined    # no question or answer text in logs


def test_group_needs_ask_command_in_the_configured_group_only():
    br, asked = make()
    assert br.handle(msg("Berapa net revenue?", chat_type="supergroup")) == "ignored"
    assert br.handle(msg("/ask Berapa?", chat_type="supergroup", chat_id=-100999)) == "ignored"
    assert br.handle(msg("/ask@other_bot Berapa?", chat_type="supergroup")) == "ignored"
    assert br.handle(msg("/ask@Astra_Bot Berapa?", chat_type="supergroup", is_topic_message=True,
                         message_thread_id=42)) == "answered"
    assert asked == [("Berapa?", f"tg-{GROUP}-{ALLOWED}")]
    assert br.tg.sent()[-1]["message_thread_id"] == "42"


@pytest.mark.parametrize("text, question", [
    ("@astra_bot Berapa net revenue 2025?", "Berapa net revenue 2025?"),
    ("Berapa net revenue 2025 @Astra_Bot", "Berapa net revenue 2025"),
    ("@astra_bot, berapa PO 2025?", "berapa PO 2025?"),
])
def test_group_mention_in_a_topic_is_a_question(text, question):
    br, asked = make()
    assert br.handle(msg(text, chat_type="supergroup", is_topic_message=True, message_thread_id=9)) == "answered"
    assert asked == [(question, f"tg-{GROUP}-{ALLOWED}")]
    assert br.tg.sent()[-1]["message_thread_id"] == "9"


@pytest.mark.parametrize("text", [
    "@someone_else Berapa?",           # another user or bot
    "@astra_botx Berapa?",             # longer username
    "mail me at x@astra_bot.com",      # not a mention
    "Berapa net revenue 2025?",        # plain group chatter
    "/start",                          # other commands
])
def test_group_messages_not_for_the_bot_are_ignored(text):
    logs = []
    br, asked = make(logs=logs)
    assert br.handle(msg(text, chat_type="supergroup")) == "ignored"
    assert asked == [] and br.tg.sent() == [] and logs == []


def test_mention_only_gives_help_and_wrong_group_is_ignored():
    br, asked = make()
    assert br.handle(msg("@astra_bot", chat_type="supergroup")) == "help"
    assert br.handle(msg("@astra_bot Berapa?", chat_type="supergroup", chat_id=-777777)) == "ignored"
    assert asked == []


def test_reply_to_the_bot_is_a_follow_up_question():
    br, asked = make()
    bot_msg = {"from": {"id": 42, "is_bot": True, "username": "Astra_Bot"}}
    human_msg = {"from": {"id": 3333, "is_bot": False, "username": "astra_bot"}}
    assert br.handle(msg("Dan untuk 2024?", chat_type="supergroup", reply_to_message=bot_msg)) == "answered"
    assert br.handle(msg("Dan untuk 2024?", chat_type="supergroup", reply_to_message=human_msg)) == "ignored"
    assert asked == [("Dan untuk 2024?", f"tg-{GROUP}-{ALLOWED}")]


def test_unauthorized_mention_is_refused():
    br, asked = make()
    assert br.handle(msg("@astra_bot hapus data", uid=STRANGER, chat_type="supergroup")) == "refused"
    assert asked == []


def test_mentions_are_off_without_a_bot_username():
    cfg = b.config_from_env(env())
    br = b.Bridge(cfg, FakeTG(), lambda q, s: "x", clock=Clock(), log=lambda _l: None, bot_username="")
    assert br.handle(msg("@astra_bot Berapa?", chat_type="supergroup")) == "ignored"


@pytest.mark.parametrize("text", ["/start", "/help", "/ask", "/whatever"])
def test_help_in_private_chat(text):
    br, asked = make()
    assert br.handle(msg(text)) == "help"
    assert asked == [] and br.tg.sent()[-1]["text"] == b.HELP


def test_old_and_non_text_messages_are_ignored():
    br, asked = make()
    assert br.handle(msg("old question", date=1_000_000 - 3600)) == "old"
    assert br.handle({"update_id": 2, "message": {"chat": {"id": 1, "type": "private"}, "photo": []}}) == "ignored"
    assert br.handle({"update_id": 3, "edited_message": {}}) == "ignored"
    assert asked == []


def test_too_long_question_and_rate_limit():
    br, asked = make()
    assert br.handle(msg("x" * (b.MAX_QUESTION + 1))) == "too_long"
    for _ in range(b.RATE_MAX):
        assert br.handle(msg("q")) == "answered"
    assert br.handle(msg("q")) == "limited"
    assert len(asked) == b.RATE_MAX


def test_assistant_failure_gives_a_generic_reply():
    def broken(q, s):
        raise b.AskError("webhook HTTP 500")
    logs = []
    br, _ = make(ask=broken, logs=logs)
    assert br.handle(msg("Berapa?")) == "failed"
    assert br.tg.sent()[-1]["text"] == b.UNAVAILABLE
    assert any("HTTP 500" in line for line in logs)


def test_reply_failure_does_not_raise():
    tg = FakeTG({"sendMessage": NotifyError("Telegram sendMessage failed after 1 attempt(s): HTTP 400: x")})
    br, _ = make(tg=tg)
    assert br.handle(msg("Berapa?")) == "answered"


# ---------------------------------------------------------------- polling

def test_preflight_refuses_when_a_webhook_is_set_and_never_deletes_it():
    tg = FakeTG({"getWebhookInfo": {"url": "https://example.org/hook"}})
    br, _ = make(tg=tg)
    with pytest.raises(b.BridgeConfigError, match="webhook"):
        br.preflight()
    assert [m for m, _ in tg.calls] == ["getWebhookInfo"]


def test_preflight_skips_the_backlog():
    tg = FakeTG({"getWebhookInfo": {"url": ""}, "getUpdates": [[{"update_id": 41}]]})
    br, _ = make(tg=tg)
    br.preflight()
    assert br.offset == 42


def test_poll_once_advances_the_offset_and_survives_a_bad_update():
    tg = FakeTG({"getUpdates": [[{"update_id": 5, "message": "not a dict"}, msg("Berapa?") | {"update_id": 6}]]})
    br, asked = make(tg=tg)
    assert br.poll_once() == 2
    assert br.offset == 7 and len(asked) == 1
    method, data = tg.calls[0]
    assert method == "getUpdates" and json.loads(data["allowed_updates"]) == ["message"]


def test_run_stops_on_conflict():
    tg = FakeTG({"getUpdates": NotifyError("Telegram getUpdates failed after 1 attempt(s): HTTP 409: Conflict")})
    br, _ = make(tg=tg)
    assert br.run(5, sleep=lambda s: None) == 3


def test_run_gives_up_after_bounded_consecutive_errors():
    tg = FakeTG({"getUpdates": NotifyError("Telegram getUpdates failed: network error (OSError)")})
    sleeps = []
    br, _ = make(tg=tg)
    assert br.run(60, sleep=sleeps.append) == 1
    assert len(sleeps) == b.MAX_CONSECUTIVE_ERRORS - 1 and max(sleeps) <= 60


def test_run_ends_at_the_time_limit():
    clock = Clock()
    tg = FakeTG()

    def get_updates(method, data):
        clock.t += 30
        return []
    tg.call = get_updates
    br, _ = make(tg=tg, clock=clock)
    assert br.run(1, sleep=lambda s: None) == 0


# ---------------------------------------------------------------- webhook client

def test_asker_posts_question_with_header_token():
    seen = {}

    def post(url, body, headers, timeout):
        seen.update(url=url, body=body, headers=headers, timeout=timeout)
        return 200, json.dumps({"output": " jawaban "}).encode()
    cfg = b.config_from_env(env())
    assert b.make_asker(cfg, post=post)("Berapa?", "tg-1-1") == "jawaban"
    assert seen["url"] == b.DEFAULT_WEBHOOK_URL
    assert seen["body"] == {"chatInput": "Berapa?", "sessionId": "tg-1-1"}
    assert seen["headers"] == {b.WEBHOOK_HEADER: WTOKEN} and seen["timeout"] >= 120


@pytest.mark.parametrize("result, text", [
    ((401, b""), "HTTP 401"),
    ((200, b"<html>"), "not JSON"),
    ((200, b'{"output": ""}'), "empty"),
    (urllib.error.URLError("refused"), "unreachable"),
])
def test_asker_errors_hold_no_secrets(result, text):
    def post(url, body, headers, timeout):
        if isinstance(result, Exception):
            raise result
        return result
    with pytest.raises(b.AskError, match=text) as e:
        b.make_asker(b.config_from_env(env()), post=post)("q", "s")
    assert WTOKEN not in str(e.value)


@pytest.mark.parametrize("raw, want", [
    ("## Ringkasan\n**Net revenue 2025**: Rp 54.269.362.661.171", "Ringkasan\nNet revenue 2025: Rp 54.269.362.661.171"),
    ("* Bandung\n  * Sunter\n+ Bekasi", "- Bandung\n  - Sunter\n- Bekasi"),
    ("Pakai `.\\astra fix` dan __jangan__ *ubah*", "Pakai .\\astra fix dan jangan ubah"),
    ("- sudah polos\n\nbaris 2", "- sudah polos\n\nbaris 2"),
    ("Kode #A12 tetap", "Kode #A12 tetap"),   # a '#' that is not a heading stays
])
def test_plain_text_removes_markdown(raw, want):
    assert b.plain_text(raw) == want


def test_asker_returns_plain_text_and_rejects_markdown_only_answers():
    cfg = b.config_from_env(env())
    ok = b.make_asker(cfg, post=lambda *a: (200, json.dumps({"output": "**Rp 1**"}).encode()))
    assert ok("q", "s") == "Rp 1"
    empty = b.make_asker(cfg, post=lambda *a: (200, json.dumps({"output": "** **"}).encode()))
    with pytest.raises(b.AskError, match="empty"):
        empty("q", "s")
