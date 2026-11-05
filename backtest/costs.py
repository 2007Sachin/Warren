"""Angel One cash-market costs. All rates are fractions of notional unless noted.

Brokerage is Rs 20 flat per executed order for MIS and CNC.
Exchange txn 0.000345 is applied as 0.000345% of notional (same units as
the other percent figures in the Phase 2 spec).
SEBI is Rs 10 per crore of notional.
"""
from __future__ import annotations

BROKERAGE_FLAT = 20.0
STT_MIS_SELL = 0.00025       # 0.025%
STT_CNC = 0.001              # 0.1% both sides
STAMP_BUY = 0.00003          # 0.003%
EXCHANGE_TXN = 0.000345 / 100
SEBI_PER_CRORE = 10.0
GST_RATE = 0.18
SLIPPAGE = 0.0005            # 0.05% per side
CRORE = 10_000_000.0


def order_cost(side: str, product: str, qty: float, price: float) -> dict:
    """Full per-executed-order breakdown. `side` is BUY or SELL; `product` is MIS or CNC."""
    side = side.upper()
    product = product.upper()
    if qty <= 0 or price <= 0:
        return {
            "side": side,
            "product": product,
            "qty": 0.0,
            "price": float(price),
            "notional": 0.0,
            "brokerage": 0.0,
            "stt": 0.0,
            "stamp": 0.0,
            "exchange_txn": 0.0,
            "sebi": 0.0,
            "gst": 0.0,
            "slippage": 0.0,
            "total": 0.0,
        }
    notional = float(qty) * float(price)
    brokerage = BROKERAGE_FLAT
    if product == "MIS":
        stt = notional * STT_MIS_SELL if side == "SELL" else 0.0
    else:
        stt = notional * STT_CNC
    stamp = notional * STAMP_BUY if side == "BUY" else 0.0
    exchange_txn = notional * EXCHANGE_TXN
    sebi = notional / CRORE * SEBI_PER_CRORE
    gst = GST_RATE * (brokerage + exchange_txn + sebi)
    slippage = notional * SLIPPAGE
    total = brokerage + stt + stamp + exchange_txn + sebi + gst + slippage
    return {
        "side": side,
        "product": product,
        "qty": float(qty),
        "price": float(price),
        "notional": notional,
        "brokerage": brokerage,
        "stt": stt,
        "stamp": stamp,
        "exchange_txn": exchange_txn,
        "sebi": sebi,
        "gst": gst,
        "slippage": slippage,
        "total": total,
    }


def round_trip_cost(product: str, qty: float, buy_price: float, sell_price: float) -> dict:
    buy = order_cost("BUY", product, qty, buy_price)
    sell = order_cost("SELL", product, qty, sell_price)
    keys = ["brokerage", "stt", "stamp", "exchange_txn", "sebi", "gst", "slippage", "total"]
    merged = {k: buy[k] + sell[k] for k in keys}
    merged["buy"] = buy
    merged["sell"] = sell
    return merged
