"""Limit-only paper broker. Never imports a live order gateway."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from backtest.costs import order_cost

SLIPPAGE = 0.0005


@dataclass
class PaperOrder:
    client_tag: str
    symbol: str
    side: str
    qty: int
    limit_price: float
    status: str = "PENDING"
    signal_date: date | None = None
    fill_date: date | None = None
    fill_price: float | None = None
    costs_breakdown: dict = field(default_factory=dict)
    stop_price: float | None = None
    session_open: float | None = None

    def as_dict(self) -> dict:
        d = asdict(self)
        if self.signal_date:
            d["signal_date"] = str(self.signal_date)
        if self.fill_date:
            d["fill_date"] = str(self.fill_date)
        return d


class PaperBroker:
    def __init__(self):
        self.orders: dict[str, PaperOrder] = {}

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        limit_price: float,
        client_tag: str,
        signal_date: date | None = None,
        stop_price: float | None = None,
    ) -> PaperOrder:
        if client_tag in self.orders:
            return self.orders[client_tag]
        order = PaperOrder(
            client_tag=client_tag,
            symbol=symbol,
            side=side.upper(),
            qty=int(qty),
            limit_price=float(limit_price),
            signal_date=signal_date,
            stop_price=stop_price,
        )
        self.orders[client_tag] = order
        return order

    def cancel(self, client_tag: str) -> PaperOrder | None:
        order = self.orders.get(client_tag)
        if order is None or order.status != "PENDING":
            return order
        order.status = "CANCELLED"
        return order

    def get_order_status(self, client_tag: str) -> str | None:
        order = self.orders.get(client_tag)
        return None if order is None else order.status

    def get_positions(self) -> dict[str, Any]:
        return {}

    def pending(self) -> list[PaperOrder]:
        return [o for o in self.orders.values() if o.status == "PENDING"]

    def resolve_open(self, session: date, opens: dict[str, float]) -> list[PaperOrder]:
        """Fill LIMIT orders against this session's open, else expire at day end."""
        resolved = []
        for order in list(self.pending()):
            if order.signal_date is not None and session <= order.signal_date:
                continue
            px = opens.get(order.symbol)
            if px is None or px <= 0:
                order.status = "EXPIRED"
                order.fill_date = session
                order.session_open = None
                order.costs_breakdown = {"expired_open": None, "gap_pct": None}
                resolved.append(order)
                continue
            order.session_open = float(px)
            buy_ok = order.side == "BUY" and px <= order.limit_price
            sell_ok = order.side == "SELL" and px >= order.limit_price
            if buy_ok or sell_ok:
                order.fill_price = float(px)
                order.fill_date = session
                order.status = "FILLED"
                order.costs_breakdown = order_cost(order.side, "CNC", order.qty, px)
            else:
                order.status = "EXPIRED"
                order.fill_date = session
                gap = (px / order.limit_price - 1.0) if order.limit_price else None
                order.costs_breakdown = {"expired_open": float(px), "gap_pct": gap}
            resolved.append(order)
        return resolved
