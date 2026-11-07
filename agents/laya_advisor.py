"""Laya advisor. Votes may only reduce size or skip. Mock abstains if laya missing."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from paper.ledger import append_vote

MODE_FILE = os.environ.get("LAYA_MODE_FILE", "data/store/paper/laya_mode.json")
ADVISOR = "laya"


def _laya_available() -> bool:
    if os.environ.get("LAYA_MOCK", "").lower() in {"1", "true", "yes"}:
        return False
    try:
        import laya  # noqa: F401
        return True
    except Exception:
        return False


def load_mode() -> str:
    try:
        with open(MODE_FILE) as f:
            return json.load(f).get("mode", "log-only")
    except FileNotFoundError:
        return "log-only"


def save_mode(mode: str, reason: str) -> None:
    os.makedirs(os.path.dirname(MODE_FILE) or ".", exist_ok=True)
    with open(MODE_FILE, "w") as f:
        json.dump({"mode": mode, "reason": reason}, f)


def _abstain(vote_type: str, payload: dict) -> dict:
    vote = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "advisor": ADVISOR,
        "vote_type": vote_type,
        "payload": {**payload, "vote": "no opinion", "route": "review"},
        "acted_on": False,
    }
    append_vote({**vote, "payload": json.dumps(vote["payload"])})
    return vote


def _agent():
    from laya import Agent
    return Agent(device="cpu", compile=False)


def regime_vote(state: dict) -> dict:
    if not _laya_available():
        return _abstain("regime", {"state": state})
    try:
        agent = _agent()
        out = agent.predict(
            state,
            {
                "regime": {
                    "type": "choice",
                    "instructions": "Classify the Indian cash-equity regime.",
                    "criteria": {
                        "trending": "Persistent directional move.",
                        "ranging": "Choppy, small 20-day return.",
                        "volatile": "Two-way swings.",
                        "crisis": "Sharp drawdown.",
                    },
                }
            },
        )
        ans = (out.get("answers") or {}).get("regime") or {}
        choice = ans.get("choice")
        if not choice:
            return _abstain("regime", {"state": state, "raw": out})
        vote = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "advisor": ADVISOR,
            "vote_type": "regime",
            "payload": {"choice": choice, "vote": choice, "confidence": ans.get("confidence")},
            "acted_on": load_mode() == "active",
        }
        append_vote({**vote, "payload": json.dumps(vote["payload"])})
        return vote
    except Exception:
        return _abstain("regime", {"state": state})


def triage_vote(features: dict) -> dict:
    if not _laya_available():
        return _abstain("triage", {"features": features})
    try:
        agent = _agent()
        out = agent.predict(
            features,
            {
                "quality": {
                    "type": "score",
                    "instructions": "Breakout quality 0 weak, 1 mixed, 2 strong.",
                    "criteria": ["weak or trap", "mixed", "clean continuation"],
                },
                "anomalous": {
                    "type": "noul",
                    "instructions": "Is this breakout anomalous vs ATR/volume/52w high?",
                    "criteria": {"false": "ordinary", "true": "anomalous"},
                },
            },
        )
        ans = out.get("answers") or {}
        q = ans.get("quality") or {}
        a = ans.get("anomalous") or {}
        raw_q = q.get("score", q.get("choice", 2))
        try:
            quality = max(0, min(2, int(round(float(raw_q)))))
        except Exception:
            return _abstain("triage", {"features": features, "raw": out})
        anomalous = bool((a.get("noul") or 0) > 0.5) if isinstance(a.get("noul"), (int, float)) else bool(a.get("choice"))
        vote = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "advisor": ADVISOR,
            "vote_type": "triage",
            "payload": {"quality": quality, "anomalous": anomalous, "vote": quality},
            "acted_on": load_mode() == "active",
        }
        append_vote({**vote, "payload": json.dumps(vote["payload"])})
        return vote
    except Exception:
        return _abstain("triage", {"features": features})


def size_multiplier(triage: dict, regime: dict) -> float:
    """Never greater than 1. Abstain / log-only => 1.0."""
    if load_mode() != "active":
        return 1.0
    payload = triage.get("payload") or {}
    if payload.get("vote") == "no opinion":
        return 1.0
    if payload.get("anomalous"):
        return 0.0
    reg = (regime.get("payload") or {}).get("choice")
    if reg == "crisis":
        return 0.0
    if reg == "ranging":
        return 0.5
    q = payload.get("quality")
    if q is None:
        return 1.0
    if int(q) <= 0:
        return 0.0
    if int(q) == 1:
        return 0.5
    return 1.0
