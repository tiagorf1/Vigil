"""Telegram signal notifier.

Sends a concise message to your phone when a scan surfaces something worth
looking at. Free, and works on iPhone via the Telegram app.

Setup:
  1. Message @BotFather, /newbot, copy the token -> TELEGRAM_BOT_TOKEN.
  2. Message your new bot once, then visit
     https://api.telegram.org/bot<TOKEN>/getUpdates and copy the chat id
     -> TELEGRAM_CHAT_ID.
"""

from __future__ import annotations

import logging

import httpx

from scanner.config import get_config

logger = logging.getLogger("scanner.notify")


class TelegramNotifier:
    def __init__(self):
        self.cfg = get_config()

    @property
    def enabled(self) -> bool:
        return self.cfg.telegram_enabled

    async def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                r = await client.post(url, json={
                    "chat_id": self.cfg.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
            if r.status_code != 200:
                logger.warning("Telegram send HTTP %d: %s", r.status_code, r.text[:160])
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Telegram send failed: %s", exc)
            return False


def build_signal_message(watchlist: dict) -> str | None:
    """Compose a signal message. We send the message when at least one pick
    clears the bar (or there are exits), but the message then lists EVERY pick
    on the board so nothing is missed. Each line is deliberately minimal:
    direction, entry, stop, target, conviction — nothing else to decode."""
    cfg = get_config()
    items = watchlist.get("watchlist", [])
    exits = watchlist.get("exits", [])

    def qualifies(it) -> bool:
        conv = it.get("conviction", 0) or 0
        exp = it.get("expected_return_pct")
        prob = it.get("prob_up")
        return (conv >= cfg.signal_min_conviction
                or (isinstance(exp, (int, float)) and abs(exp) >= cfg.signal_min_return)
                or (isinstance(prob, (int, float)) and (prob >= 0.65 or prob <= 0.35)))

    # Gate on whether ANYTHING is worth pinging about; if so, show the whole board.
    if not any(qualifies(it) for it in items) and not exits:
        return None

    directive = watchlist.get("directive", "")
    when = (watchlist.get("generated_at", "") or "")[:16].replace("T", " ")
    lines = [f"🛰 <b>VIGIL</b> — {_esc(directive)}", f"<i>{when} UTC</i>", ""]

    for it in items[:20]:
        rep = it.get("report", {}) or {}
        d = (it.get("direction") or rep.get("direction") or "long").lower()
        head = "📈 LONG" if d != "short" else "📉 SHORT"
        conv = int(it.get("conviction", 0) or 0)
        stars = "★" * conv + "☆" * (5 - conv)
        entry = rep.get("entry_zone") or it.get("entry_zone") or "n/a"
        stop = rep.get("stop_loss") or it.get("stop_loss") or "n/a"
        target = rep.get("target") or it.get("target") or "n/a"
        lines.append(f"{head} <b>{_esc(it.get('symbol'))}</b> {stars}")
        lines.append(f"   entry {_esc(entry)} · stop {_esc(stop)} · target {_esc(target)}")

    if exits:
        lines.append("")
        lines.append("⚠️ <b>Exit signals</b>")
        for e in exits[:6]:
            er = e.get("expected_return_pct")
            er_s = f"{er:+.1f}%" if isinstance(er, (int, float)) else "n/a"
            lines.append(f"{_esc(e.get('symbol'))} {er_s}")

    return "\n".join(lines)


def _esc(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
