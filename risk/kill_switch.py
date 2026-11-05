"""Kill switch: layered breakers. Phase 3+ wiring; kept dependency-free.

Rules (per roadmap):
1. Per-trade breaker   -> block a single bad order
2. Daily loss breaker  -> halt strategy if daily P&L < -daily_loss_limit
3. Drawdown breaker    -> flatten + disable until human re-activation
4. Health breaker      -> halt on feed/order anomalies
"""
import json, os
from dataclasses import dataclass, asdict
from datetime import date

STATE_FILE = os.environ.get("KILL_SWITCH_FILE", "data/store/kill_switch.json")


@dataclass
class KillSwitchState:
    halted: bool = False
    reason: str = ""
    date: str = ""


def load() -> KillSwitchState:
    try:
        with open(STATE_FILE) as f:
            return KillSwitchState(**json.load(f))
    except FileNotFoundError:
        return KillSwitchState()


def _save(s: KillSwitchState):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(asdict(s), f)


def trip(reason: str):
    _save(KillSwitchState(halted=True, reason=reason, date=str(date.today())))


def reset(human_confirmation: bool):
    """Kill switch requires HUMAN re-activation — never auto-reset."""
    if not human_confirmation:
        raise PermissionError("Kill switch can only be reset manually by a human.")
    _save(KillSwitchState())


def check_daily_loss(day_pnl: float, daily_loss_limit: float):
    if day_pnl <= -abs(daily_loss_limit):
        trip(f"Daily loss limit breached: {day_pnl:.2f} <= -{daily_loss_limit}")


def can_trade() -> bool:
    return not load().halted
