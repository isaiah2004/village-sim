"""
A per-resource call market (sealed-bid double auction).

Each tick agents submit buy orders (max willingness to pay) and sell orders
(min acceptable price). For each resource we find the single clearing price that
maximises traded volume: sort bids high->low and asks low->high, walk down until
the highest remaining bid can no longer meet the lowest remaining ask. Everyone
who trades does so at one clearing price -- classic supply/demand price discovery.

The market only decides *who trades how much at what price*. The World performs
the actual movement of lineage Lots and cash, because Lots live with the agents.
"""
from __future__ import annotations

from dataclasses import dataclass

from agents import Order
from config import Resource


@dataclass
class Trade:
    resource: Resource
    buyer_id: str
    seller_id: str
    qty: float
    price: float


@dataclass
class Clearing:
    resource: Resource
    price: float
    volume: float
    trades: list[Trade]


class CallMarket:
    def clear(self, resource: Resource, orders: list[Order]) -> Clearing:
        bids = sorted([o for o in orders if o.side == "buy"], key=lambda o: -o.price)
        asks = sorted([o for o in orders if o.side == "sell"], key=lambda o: o.price)

        # Find clearing volume + price by walking the crossing book.
        clearing_price, volume = self._find_clearing(bids, asks)
        trades: list[Trade] = []
        if volume <= 1e-9:
            return Clearing(resource, clearing_price, 0.0, trades)

        # Allocate `volume` to the most eager buyers and cheapest sellers,
        # all transacting at the single clearing price.
        bi = si = 0
        b_left = bids[0].qty if bids else 0.0
        s_left = asks[0].qty if asks else 0.0
        remaining = volume
        while remaining > 1e-9 and bi < len(bids) and si < len(asks):
            q = min(b_left, s_left, remaining)
            if q > 1e-9:
                trades.append(Trade(resource, bids[bi].agent_id, asks[si].agent_id, q, clearing_price))
                b_left -= q
                s_left -= q
                remaining -= q
            if b_left <= 1e-9:
                bi += 1
                if bi < len(bids):
                    b_left = bids[bi].qty
            if s_left <= 1e-9:
                si += 1
                if si < len(asks):
                    s_left = asks[si].qty
        return Clearing(resource, clearing_price, volume, trades)

    @staticmethod
    def _find_clearing(bids: list[Order], asks: list[Order]) -> tuple[float, float]:
        """
        Pick the price that maximises matched volume. demand(p) is the quantity
        bid at >= p; supply(p) the quantity asked at <= p; matched = min of the
        two. Among prices that tie on volume we take the midpoint of the tightest
        crossing bid/ask so the clearing price sits fairly between the two sides.
        """
        if not bids or not asks:
            return 0.0, 0.0
        candidates = sorted({o.price for o in bids} | {o.price for o in asks})
        best_vol = 0.0
        best_price = 0.0
        for p in candidates:
            demand = sum(o.qty for o in bids if o.price >= p)
            supply = sum(o.qty for o in asks if o.price <= p)
            vol = min(demand, supply)
            if vol > best_vol + 1e-12:
                best_vol = vol
                best_price = p
        if best_vol <= 1e-9:
            return 0.0, 0.0
        # Fair price: midpoint between the marginal (last matched) bid and ask.
        marg_bid = CallMarket._marginal_price(bids, best_vol, high_first=True)
        marg_ask = CallMarket._marginal_price(asks, best_vol, high_first=False)
        fair = (marg_bid + marg_ask) / 2.0
        return fair, best_vol

    @staticmethod
    def _marginal_price(orders: list[Order], volume: float, high_first: bool) -> float:
        ordered = sorted(orders, key=lambda o: (-o.price if high_first else o.price))
        acc = 0.0
        price = ordered[0].price
        for o in ordered:
            price = o.price
            acc += o.qty
            if acc >= volume - 1e-9:
                break
        return price
