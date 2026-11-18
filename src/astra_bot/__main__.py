r"""CLI for the Telegram bridge (doc 36). From the project folder, in PowerShell or cmd:

  .\astra telegram-bot check              check the .env settings (no network)
  .\astra telegram-bot check --online     also ask Telegram for the bot name and webhook state (sends nothing)
  .\astra telegram-bot run [--minutes N]  answer questions until the time limit (default 480, max 1440)

Stop with Ctrl+C. Nothing listens on a port: the bridge only makes outbound calls.
"""
from __future__ import annotations

import argparse
import sys
import time

from astra_bot.bridge import Bridge, BridgeConfigError, config_from_env, make_asker, polling_client
from astra_etl.notify import NotifyError


def _log(line: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=".\\astra telegram-bot", description="Telegram bridge for the data assistant")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check the settings")
    c.add_argument("--online", action="store_true", help="also call getMe and getWebhookInfo (sends no message)")
    r = sub.add_parser("run", help="answer questions until the time limit")
    r.add_argument("--minutes", type=float, default=480.0)
    a = ap.parse_args(argv)

    from astra_etl.db import load_env
    try:
        cfg = config_from_env(load_env())
    except (BridgeConfigError, RuntimeError) as e:
        print(f"config error: {e}")
        return 2
    print(f"config OK: {len(cfg.allowed_users)} allowed user(s), group /ask "
          f"{'on' if cfg.group_chat_id else 'off'}, webhook {cfg.webhook_url}")
    if a.cmd == "check" and not a.online:
        return 0
    tg = polling_client(cfg)
    try:
        me = tg.call("getMe", {})
        info = tg.call("getWebhookInfo", {})
    except NotifyError as e:
        print(f"Telegram error: {e}")
        return 1
    print(f"bot @{me.get('username', '?')}; Telegram webhook {'SET (bridge cannot run)' if info.get('url') else 'not set'}")
    if a.cmd == "check":
        return 3 if info.get("url") else 0
    if not 1 <= a.minutes <= 1440:
        print("--minutes must be between 1 and 1440")
        return 2
    if not me.get("username"):
        print("Telegram returned no bot username; /ask@<bot> could not be checked, so the bridge does not start")
        return 1
    bridge = Bridge(cfg, tg, make_asker(cfg), log=_log, bot_username=me.get("username", ""))
    try:
        bridge.preflight()
        _log(f"running for {a.minutes:.0f} min; Ctrl+C stops")
        return bridge.run(a.minutes)
    except BridgeConfigError as e:
        _log(f"stopped: {e}")
        return 3
    except NotifyError as e:
        _log(f"stopped: {e}")
        return 1
    except KeyboardInterrupt:
        _log(f"stopped by Ctrl+C; {bridge.stats}")
        return 0
    except Exception as e:  # last resort: error class only, never the message (it could hold data)
        _log(f"stopped: unexpected {type(e).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
