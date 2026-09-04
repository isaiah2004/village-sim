"""
Resource lineage DAG + credit propagation.

This is the backbone of the "downstream contribution tracking" (brief section 8)
and -- because credit is only paid when a resource does *realized* economic work --
also the anti-exploitation mechanism (section 7).

Every unit of resource that is produced becomes a Lot. A Lot remembers who made
it and, if it was crafted from other resources, which Lots were its inputs
(`parents`). Ownership can change hands through the market, but provenance does
not: the original producer is forever recorded.

When a resource later produces a *stabilizing effect* (e.g. wood actually burned
by a cold villager in winter), we attribute a value to the Lot that was consumed
and propagate that credit BACKWARD through the DAG, attenuating by `lam` at each
hop, so that earlier/foundational contributors receive proportional credit.

    Tree -> Wood -> Tool -> (extra wood gathered) -> burned in winter
    credit flows the other way, paying the tool's crafter and the original
    wood gatherer a diminishing share.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from config import Resource


@dataclass
class Lot:
    id: int
    resource: Resource
    producer_id: str
    tick: int
    kind: str                                  # "gather" | "craft"
    # parents: (parent_lot_id, weight) -- weights are relative input contributions
    parents: list[tuple[int, float]] = field(default_factory=list)
    qty_produced: float = 0.0
    credit_paid: float = 0.0                   # cumulative reward propagated to/through this lot


class LineageGraph:
    """Global registry of all Lots ever produced, with backward credit flow."""

    def __init__(self) -> None:
        self.lots: dict[int, Lot] = {}
        self._next_id = 1

    def new_lot(
        self,
        resource: Resource,
        producer_id: str,
        tick: int,
        kind: str,
        qty: float,
        parents: list[tuple[int, float]] | None = None,
    ) -> Lot:
        lot = Lot(
            id=self._next_id,
            resource=resource,
            producer_id=producer_id,
            tick=tick,
            kind=kind,
            parents=parents or [],
            qty_produced=qty,
        )
        self.lots[lot.id] = lot
        self._next_id += 1
        return lot

    def propagate_credit(
        self,
        lot_id: int,
        value: float,
        lam: float,
        pay: Callable[[str, float, Lot], None],
    ) -> None:
        """
        Distribute `value` of realized contribution onto `lot_id` and recursively
        upstream. The lot's own producer keeps (1 - lam) of the value flowing
        through it; the remaining `lam` fraction is split across its parents by
        weight and recursed. Raw (parent-less) lots keep the full remaining value.
        """
        lot = self.lots.get(lot_id)
        if lot is None or value <= 1e-9:
            return
        # total_w = fraction of this lot attributable to its inputs (0..1):
        #   crafted goods -> ~1.0 (all material came from parents)
        #   tool-boosted gathering -> just the extra yield the tool enabled
        total_w = sum(w for _, w in lot.parents)
        upstream = value * lam * min(1.0, total_w) if lot.parents else 0.0
        direct = value - upstream
        lot.credit_paid += direct
        pay(lot.producer_id, direct, lot)
        if total_w > 1e-9:
            for parent_id, w in lot.parents:
                self.propagate_credit(parent_id, upstream * (w / total_w), lam, pay)
