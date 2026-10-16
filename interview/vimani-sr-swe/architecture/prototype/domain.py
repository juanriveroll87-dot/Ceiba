"""Deterministic core: the system of record.

Nothing in this module calls an LLM. Every number that can cost money
(quantities, prices, dates, budget exposure) is computed here, from data,
by code that can be unit-tested. The AI layer reads from here and *proposes*
calls into here; it never writes state directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

D = Decimal


@dataclass(frozen=True)
class Contact:
    role: str      # "supplier", "compras", "residente", "cuentas_por_pagar", "DRO", ...
    name: str
    channel: str   # "whatsapp", "email", "app"
    external: bool = False


@dataclass(frozen=True)
class Offer:
    supplier: str
    material: str
    unit_price: Decimal
    lead_days: int


@dataclass
class POLine:
    key: str
    supplier: str
    material: str
    unit: str
    ordered: Decimal
    unit_price: Decimal
    cost_code: str
    received: Decimal = D(0)
    rejected: Decimal = D(0)

    @property
    def open_qty(self) -> Decimal:
        # Rejected material is still owed by the supplier.
        return self.ordered - self.received


@dataclass
class Task:
    id: str
    name: str
    start: date
    needs: dict[str, Decimal] = field(default_factory=dict)
    successors: list[str] = field(default_factory=list)
    rebooking_fee: Decimal = D(0)        # e.g. concrete pump booked for that day
    split_extra_cost: Decimal | None = None
    split_requires: tuple[str, ...] = ()
    foreman: str | None = None


@dataclass(frozen=True)
class Event:
    kind: str
    data: dict


@dataclass(frozen=True)
class Shortfall:
    task_id: str
    material: str
    needed: Decimal
    available: Decimal
    gap: Decimal
    needed_on: date  # material must be on site the day before the task starts


class DomainError(ValueError):
    pass


@dataclass
class Site:
    name: str
    today: date
    inventory: dict[str, Decimal]
    po_lines: dict[str, POLine]
    tasks: dict[str, Task]
    offers: list[Offer]
    contacts: dict[str, Contact]
    budget: dict[str, Decimal]
    exposure: dict[str, Decimal]
    daily_indirect_cost: Decimal
    indirect_cost_code: str
    events: list[Event] = field(default_factory=list)
    _ncr_seq: int = 0

    # ------------------------------------------------------------ commands
    def record_receipt(
        self, po_key: str, accepted: Decimal, rejected: Decimal, defect: str, evidence: list[str]
    ) -> list[Event]:
        """Partial acceptance of a delivery. Validates everything before mutating."""
        line = self.po_lines.get(po_key)
        if line is None:
            raise DomainError(f"unknown PO line {po_key}")
        if accepted < 0 or rejected < 0:
            raise DomainError("quantities cannot be negative")
        if accepted + rejected > line.open_qty:
            raise DomainError(
                f"{accepted + rejected} {line.unit} exceeds open quantity {line.open_qty}"
            )

        line.received += accepted
        line.rejected += rejected
        self.inventory[line.material] = self.inventory.get(line.material, D(0)) + accepted

        new = [Event("GoodsReceived", {"po": po_key, "material": line.material,
                                       "qty": accepted, "unit": line.unit})]
        if rejected:
            self._ncr_seq += 1
            ncr = f"NCR-{self._ncr_seq:03d}"
            hold = rejected * line.unit_price
            new += [
                Event("GoodsRejected", {"po": po_key, "material": line.material, "qty": rejected,
                                        "unit": line.unit, "defect": defect, "ncr": ncr,
                                        "supplier": line.supplier, "evidence": evidence}),
                Event("NonConformanceOpened", {"ncr": ncr, "po": po_key, "qty": rejected}),
                Event("InvoiceHoldPlaced", {"po": po_key, "amount": hold, "ncr": ncr}),
            ]
        self.events += new
        return new

    # ------------------------------------------------------------ queries
    def shortfalls(self, horizon_days: int = 14) -> list[Shortfall]:
        """Walk upcoming tasks in start order, consuming stock as each one would."""
        stock = dict(self.inventory)
        horizon = self.today + timedelta(days=horizon_days)
        result = []
        for task in sorted(self.tasks.values(), key=lambda t: t.start):
            if task.start > horizon:
                break
            for material, needed in task.needs.items():
                available = stock.get(material, D(0))
                if available < needed:
                    result.append(Shortfall(task.id, material, needed, available,
                                            needed - available,
                                            task.start - timedelta(days=1)))
                stock[material] = max(D(0), available - needed)
        return result

    def propagate_delay(self, task_id: str, days: int) -> dict[str, int]:
        """Finish-to-start, no float: a delay shifts every downstream task."""
        if days <= 0:
            return {}
        shifted, queue = {}, [task_id]
        while queue:
            current = queue.pop()
            if current in shifted:
                continue
            shifted[current] = days
            queue.extend(self.tasks[current].successors)
        return shifted

    def delay_cost(self, shifted: dict[str, int]) -> Decimal:
        if not shifted:
            return D(0)
        days = max(shifted.values())
        fees = sum((self.tasks[t].rebooking_fee for t in shifted), D(0))
        return self.daily_indirect_cost * days + fees

    def budget_pct(self, code: str, extra: Decimal = D(0)) -> Decimal:
        return ((self.exposure[code] + extra) / self.budget[code] * 100).quantize(D("0.1"))

    def open_ncr_material(self) -> set[str]:
        open_ncrs = {e.data["ncr"] for e in self.events if e.kind == "NonConformanceOpened"}
        return {e.data["material"] for e in self.events
                if e.kind == "GoodsRejected" and e.data["ncr"] in open_ncrs}
