r"""Telegram -> n8n data assistant bridge. Outbound connections only: nothing listens on any port.

The bridge long-polls Telegram (getUpdates), accepts questions only from the user ids in
TELEGRAM_ALLOWED_USER_IDS, forwards each question to the n8n webhook on 127.0.0.1 and sends the
assistant's answer back as plain text. No public webhook, no tunnel. Answers come from the fixed,
read-only tools of the n8n workflow (aggregates only, no personal data).

Rules:
- Default deny: an empty or malformed allow-list means the bridge does not start.
- Private chat with the bot: any text is a question. In the configured group (TELEGRAM_CHAT_ID):
  "/ask <question>", a message that mentions @<bot>, or a reply to one of the bot's messages
  (mentions and replies need privacy mode off in @BotFather). Other group messages are dropped
  without a log line. Other chats are ignored.
- The webhook URL must be on a loopback host. The webhook token goes in a request header only.
- If the bot already has a Telegram webhook set somewhere else, the bridge stops and leaves it alone
  (getUpdates would conflict). It never calls deleteWebhook.
- Messages sent before the bridge started are skipped.
- Logs hold user ids, chat types, lengths and error classes, never the question, the answer or a token.
"""
from __future__ import annotations

import dataclasses
import http.client
import ipaddress
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from typing import Callable

from astra_etl.notify import MAX_TEXT, TOKEN_RE, NotifyError, Telegram, TelegramConfig

DEFAULT_WEBHOOK_URL = "http://127.0.0.1:5698/webhook/astra-assistant"
WEBHOOK_HEADER = "X-Astra-Token"
MAX_QUESTION = 1000
RATE_MAX, RATE_WINDOW = 6, 300.0        # questions per user per 5 minutes
REFUSAL_INTERVAL = 60.0                  # at most one "not authorized" reply per user per minute
POLL_SECONDS = 25                        # Telegram long-poll timeout
MAX_CONSECUTIVE_ERRORS = 20
MAX_TRACKED_USERS = 1000                 # cap on the refusal-time table

HELP = ("Astra data assistant (SYNTHETIC data, read-only).\n"
        "Ask about sales, service, procurement, inventory, expenses, attendance or data quality, "
        "for example: Berapa net revenue 2025?\n"
        "In the group, start with /ask, mention the bot, or reply to one of its answers. "
        "The assistant cannot change data and has no personal data.")
NOT_ALLOWED = "Not authorized for this bot."
UNAVAILABLE = "The data assistant is not available right now. Try again later."
TOO_LONG = f"Question too long (max {MAX_QUESTION} characters)."
SLOW_DOWN = "Too many questions. Wait a few minutes and try again."


class BridgeConfigError(ValueError):
    """Bad or missing configuration. The message never contains a value."""


class AskError(RuntimeError):
    """The n8n webhook did not answer. The message holds only a status or an error class."""


@dataclasses.dataclass(frozen=True)
class BridgeConfig:
    token: str
    allowed_users: frozenset[int]
    group_chat_id: int | None
    webhook_url: str
    webhook_token: str

    def __repr__(self) -> str:  # never show secrets or ids
        return (f"BridgeConfig(allowed_users={len(self.allowed_users)}, group={'set' if self.group_chat_id else None}, "
                f"webhook_url={self.webhook_url!r})")


def _loopback(host: str) -> bool:
    """IP literals only: a name such as localhost depends on the hosts file / resolver."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def config_from_env(env: dict[str, str]) -> BridgeConfig:
    # A dedicated assistant bot is preferred: the alert bot may already deliver its messages to a webhook.
    key = "TELEGRAM_ASSISTANT_BOT_TOKEN" if (env.get("TELEGRAM_ASSISTANT_BOT_TOKEN") or "").strip() \
        else "TELEGRAM_BOT_TOKEN"
    token = (env.get(key) or "").strip()
    if not TOKEN_RE.match(token):
        raise BridgeConfigError(f"{key} is empty or does not look like a bot token")
    raw_users = (env.get("TELEGRAM_ALLOWED_USER_IDS") or "").strip()
    parts = [p.strip() for p in raw_users.split(",") if p.strip()]
    if not parts:
        raise BridgeConfigError("TELEGRAM_ALLOWED_USER_IDS is empty: nobody would be allowed, so the bridge "
                                "does not start. Put your numeric Telegram user id there (comma-separated for more)")
    if not all(re.fullmatch(r"\d{1,15}", p) for p in parts):
        raise BridgeConfigError("TELEGRAM_ALLOWED_USER_IDS must be numeric user ids separated by commas")
    chat = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    if chat and not re.fullmatch(r"-?\d{5,20}", chat):
        raise BridgeConfigError("TELEGRAM_CHAT_ID must be a numeric chat id or empty")
    url = (env.get("ASTRA_ASSISTANT_WEBHOOK_URL") or "").strip() or DEFAULT_WEBHOOK_URL
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname or not _loopback(u.hostname):
        raise BridgeConfigError("ASTRA_ASSISTANT_WEBHOOK_URL must be http(s) on a loopback IP (127.0.0.1 or [::1])")
    if u.username or u.password or u.query or u.fragment:
        raise BridgeConfigError("ASTRA_ASSISTANT_WEBHOOK_URL must not carry credentials, a query or a fragment")
    wtoken = (env.get("ASTRA_ASSISTANT_WEBHOOK_TOKEN") or "").strip()
    if len(wtoken) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", wtoken):
        raise BridgeConfigError("ASTRA_ASSISTANT_WEBHOOK_TOKEN must be at least 32 letters/digits/-/_ "
                                "(the same value as the n8n header credential)")
    return BridgeConfig(token, frozenset(int(p) for p in parts), int(chat) if chat else None, url, wtoken)


# ---------------------------------------------------------------- n8n webhook client

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # never follow a redirect away from loopback
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _http_post_json(url: str, body: dict, headers: dict, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(200_000)
    except urllib.error.HTTPError as e:
        return e.code, b""


def make_asker(cfg: BridgeConfig, post: Callable = _http_post_json, timeout: float = 180.0
               ) -> Callable[[str, str], str]:
    def ask(question: str, session_id: str) -> str:
        try:
            status, raw = post(cfg.webhook_url, {"chatInput": question, "sessionId": session_id},
                               {WEBHOOK_HEADER: cfg.webhook_token}, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise AskError(f"webhook unreachable ({type(e).__name__})") from None
        if status != 200:
            raise AskError(f"webhook HTTP {status}")
        try:
            out = json.loads(raw.decode("utf-8")).get("output")
        except (ValueError, AttributeError):
            raise AskError("webhook answer is not JSON with an 'output' field") from None
        if not isinstance(out, str) or not out.strip():
            raise AskError("webhook answer is empty")
        return out.strip()
    return ask


# ---------------------------------------------------------------- bridge

class Bridge:
    """Handles Telegram updates. Telegram client, asker, clock and log are injectable for tests."""

    def __init__(self, cfg: BridgeConfig, tg: Telegram, ask: Callable[[str, str], str],
                 clock: Callable = time.time, log: Callable = print, bot_username: str = ""):
        self.cfg, self.tg, self.ask, self.clock, self.log = cfg, tg, ask, clock, log
        self.bot_username = bot_username.lower()
        self.started = clock()
        self.offset: int | None = None
        self._asked: dict[int, deque[float]] = defaultdict(deque)
        self._refused: dict[int, float] = {}
        self.stats = {"answered": 0, "refused": 0, "ignored": 0, "failed": 0, "limited": 0}

    # -- sending
    def _reply(self, msg: dict, text: str) -> None:
        data = {"chat_id": str(msg["chat"]["id"]), "text": text[:MAX_TEXT],
                "disable_web_page_preview": "true", "reply_to_message_id": str(msg.get("message_id", ""))}
        if msg.get("is_topic_message") and msg.get("message_thread_id"):
            data["message_thread_id"] = str(msg["message_thread_id"])
        try:
            self.tg.call("sendMessage", data)
        except NotifyError as e:
            self.log(f"reply failed: {e}")

    def _typing(self, msg: dict) -> None:
        data = {"chat_id": str(msg["chat"]["id"]), "action": "typing"}
        if msg.get("is_topic_message") and msg.get("message_thread_id"):
            data["message_thread_id"] = str(msg["message_thread_id"])
        try:
            self.tg.call("sendChatAction", data)
        except NotifyError:
            pass

    # -- parsing
    def _question(self, msg: dict) -> str | None:
        """The question text, '' for a help request, None when the message is not for the bot."""
        text = (msg.get("text") or "").strip()
        chat = msg.get("chat") or {}
        m = re.match(r"^/(\w+)(?:@(\w+))?(?:\s+(.*))?$", text, re.S)
        if m and m.group(2) and self.bot_username and m.group(2).lower() != self.bot_username:
            return None                                   # a command for another bot
        cmd, rest = (m.group(1).lower(), (m.group(3) or "").strip()) if m else (None, text)
        if chat.get("type") == "private":
            if cmd in ("start", "help"):
                return ""
            if cmd == "ask" or cmd is None:
                return rest
            return ""
        if chat.get("type") in ("group", "supergroup") and chat.get("id") == self.cfg.group_chat_id:
            if cmd == "ask":
                return rest
            if cmd == "help":
                return ""
            if cmd is not None:
                return None                               # other commands are not for the bridge
            if self._mentions_bot(text):                  # "@bot question" anywhere in the message
                return self._strip_mention(text)
            if self._replies_to_bot(msg):                 # a reply to one of the bot's answers
                return text
        return None

    def _mention_re(self) -> re.Pattern | None:
        if not self.bot_username:
            return None
        return re.compile(r"(?<![\w@])@" + re.escape(self.bot_username) + r"(?!\w)", re.I)

    def _mentions_bot(self, text: str) -> bool:
        rx = self._mention_re()
        return bool(rx and rx.search(text))

    def _strip_mention(self, text: str) -> str:
        rx = self._mention_re()
        cleaned = rx.sub(" ", text) if rx else text
        return re.sub(r"\s+", " ", cleaned).strip(" ,:;-")

    def _replies_to_bot(self, msg: dict) -> bool:
        author = (msg.get("reply_to_message") or {}).get("from") or {}
        return bool(self.bot_username and author.get("is_bot")
                    and (author.get("username") or "").lower() == self.bot_username)

    def _rate_ok(self, uid: int) -> bool:
        now, q = self.clock(), self._asked[uid]
        while q and now - q[0] >= RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_MAX:
            return False
        q.append(now)
        return True

    # -- one update
    def handle(self, update: dict) -> str:
        msg = update.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("text"), str):
            self.stats["ignored"] += 1
            return "ignored"
        if float(msg.get("date") or 0) < self.started - 5:
            self.stats["ignored"] += 1
            return "old"
        question = self._question(msg)
        if question is None:
            self.stats["ignored"] += 1
            return "ignored"
        uid = int((msg.get("from") or {}).get("id") or 0)
        ctype = msg["chat"].get("type")
        if uid not in self.cfg.allowed_users:
            self.stats["refused"] += 1
            now = self.clock()
            if now - self._refused.get(uid, -1e9) >= REFUSAL_INTERVAL:   # one reply + log line per user per minute
                if len(self._refused) >= MAX_TRACKED_USERS:
                    self._refused = {u: t for u, t in self._refused.items() if now - t < REFUSAL_INTERVAL}
                self._refused[uid] = now
                self.log(f"refused: user id {uid} is not in TELEGRAM_ALLOWED_USER_IDS ({ctype} chat)")
                self._reply(msg, NOT_ALLOWED)
            return "refused"
        if question == "":
            self._reply(msg, HELP)
            return "help"
        if len(question) > MAX_QUESTION:
            self._reply(msg, TOO_LONG)
            return "too_long"
        if not self._rate_ok(uid):
            self.stats["limited"] += 1
            self._reply(msg, SLOW_DOWN)
            return "limited"
        self._typing(msg)
        session = f"tg-{msg['chat']['id']}-{uid}"
        t0 = self.clock()
        try:
            answer = self.ask(question, session)
        except AskError as e:
            self.stats["failed"] += 1
            self.log(f"ask failed for user {uid}: {e}")
            self._reply(msg, UNAVAILABLE)
            return "failed"
        self.stats["answered"] += 1
        self.log(f"answered user {uid} ({ctype}): question {len(question)} chars, "
                 f"answer {len(answer)} chars, {self.clock() - t0:.0f}s")
        self._reply(msg, answer)
        return "answered"

    # -- polling
    def preflight(self) -> None:
        """Stop if a webhook is set (would conflict), then skip the backlog."""
        info = self.tg.call("getWebhookInfo", {})
        if info.get("url"):
            raise BridgeConfigError("this bot has a Telegram webhook set (another service receives its "
                                    "messages). The bridge does not remove it; use another bot or ask its owner")
        pending = self.tg.call("getUpdates", {"offset": "-1", "timeout": "0"})
        if pending:
            self.offset = int(pending[-1]["update_id"]) + 1
            self.log("skipped messages sent before the bridge started")

    def poll_once(self) -> int:
        data = {"timeout": str(POLL_SECONDS), "allowed_updates": json.dumps(["message"])}
        if self.offset is not None:
            data["offset"] = str(self.offset)
        updates = self.tg.call("getUpdates", data) or []
        for u in updates:
            self.offset = int(u["update_id"]) + 1
            try:
                self.handle(u)
            except Exception as e:  # one bad update must not stop the bridge
                self.stats["failed"] += 1
                self.log(f"update skipped ({type(e).__name__})")
        return len(updates)

    def run(self, minutes: float, sleep: Callable = time.sleep) -> int:
        """Poll until the time limit. Exit code 0 at the limit, 1 after too many consecutive errors,
        3 on a polling conflict (another getUpdates client or a webhook)."""
        deadline = self.clock() + minutes * 60
        errors = 0
        while self.clock() < deadline:
            try:
                self.poll_once()
                errors = 0
            except (NotifyError, ValueError, KeyError, TypeError, http.client.HTTPException) as e:
                if isinstance(e, NotifyError) and "HTTP 409" in str(e):
                    self.log("stopped: another program is reading this bot's updates (HTTP 409 conflict)")
                    return 3
                errors += 1
                detail = str(e) if isinstance(e, NotifyError) else type(e).__name__
                self.log(f"poll error {errors}/{MAX_CONSECUTIVE_ERRORS}: {detail}")
                if errors >= MAX_CONSECUTIVE_ERRORS:
                    return 1
                sleep(min(2 ** errors, 60))
        self.log(f"time limit reached; {self.stats}")
        return 0


def polling_client(cfg: BridgeConfig, **kw) -> Telegram:
    """Long-poll client: HTTP timeout above the poll timeout; one attempt (the run loop backs off)."""
    return Telegram(TelegramConfig(cfg.token, str(cfg.group_chat_id or "0")),
                    timeout=POLL_SECONDS + 15, max_attempts=kw.pop("max_attempts", 2), **kw)
