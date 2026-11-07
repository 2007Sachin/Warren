"""Telegram summaries. Dry-run prints to stdout; never places orders."""
from __future__ import annotations

import os

from risk.kill_switch import can_trade, load, trip


def _creds() -> tuple[str, str]:
    return os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")


def send(text: str, *, dry_run: bool = True) -> str:
    body = text.rstrip() + "\n"
    if dry_run:
        print("TELEGRAM_DRY_RUN\n" + body)
        return body
    token, chat = _creds()
    if not token or not chat:
        print("TELEGRAM_DRY_RUN (missing TELEGRAM_BOT_TOKEN/CHAT_ID)\n" + body)
        return body
    import requests
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text},
        timeout=20,
    )
    return body


def handle_command(text: str) -> str:
    cmd = (text or "").strip().upper()
    if cmd == "STOP":
        trip("telegram STOP")
        return "Kill switch TRIPPED. Human reset required."
    if cmd == "STATUS":
        st = load()
        return (
            f"halted={st.halted} reason={st.reason or '-'} "
            f"can_trade={can_trade()}"
        )
    return "unknown command"


def summary_text(payload: dict) -> str:
    lines = [
        f"Warren paper {payload.get('session')}",
        f"equity={payload.get('equity'):.0f} dd={100.0 * float(payload.get('drawdown') or 0):.2f}%",
        f"signals={payload.get('n_signals', 0)} fills={payload.get('n_fills', 0)} expired={payload.get('n_expired', 0)}",
        f"open={payload.get('n_open', 0)} halted={payload.get('halted')}",
    ]
    for row in payload.get("fill_lines") or []:
        lines.append(row)
    return "\n".join(lines)
