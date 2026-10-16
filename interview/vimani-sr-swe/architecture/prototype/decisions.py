"""Consequence engine and action policy, both deterministic.

The AI may *suggest* an option, including one the supervisor typed in free
text ("¿y si usamos las varillas dañadas?"), but it has to be one of the option
kinds below. Each kind has a simulator that computes cost, delay, budget impact
and required approvals from data. Unknown kinds are rejected, not guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from domain import D, Shortfall, Site

OPTION_KINDS = ("wait_for_replacement", "buy_from_alternate", "split_task", "use_rejected_material")

# Who must approve each action before it executes. "auto" = reversible and
# internal; anything external, money-moving or structural needs a person.
ACTION_POLICY = {
    "record_receipt":         "confirm:supervisor",
    "open_ncr":               "auto",
    "hold_invoice":           "auto",
    "notify_internal":        "auto",
    "message_supplier":       "approve:compras",
    "purchase_order":         "approve:residente",
    "purchase_order_large":   "approve:gerente",   # above LARGE_PURCHASE
    "reschedule":             "approve:residente",
    "structural_change":      "approve:DRO",
}
LARGE_PURCHASE = D(50_000)


@dataclass(frozen=True)
class Consequences:
    option: str
    title: str
    cash_out: Decimal          # new money committed now
    net_cost: Decimal          # true cost after recoveries (used for ranking)
    delay_days: int
    shifted_tasks: tuple[str, ...]
    budget_after: dict[str, Decimal]  # code -> % of budget used
    approvals: tuple[str, ...]
    decide_by: date | None
    blocked: str | None = None
    notes: tuple[str, ...] = ()


def evaluate(site: Site, gap: Shortfall, kind: str, **params) -> Consequences:
    if kind not in OPTION_KINDS:
        raise ValueError(f"unknown option kind {kind!r}")
    return _SIMULATORS[kind](site, gap, **params)


def candidate_options(site: Site, gap: Shortfall) -> list[Consequences]:
    """Every option the data supports, evaluated and ranked. Blocked ones last."""
    options = [evaluate(site, gap, "wait_for_replacement")]
    for offer in site.offers:
        if offer.material == gap.material and offer.supplier != _po_for(site, gap).supplier:
            options.append(evaluate(site, gap, "buy_from_alternate", supplier=offer.supplier))
    if site.tasks[gap.task_id].split_extra_cost is not None:
        options.append(evaluate(site, gap, "split_task"))
    return rank(options)


def rank(options: list[Consequences]) -> list[Consequences]:
    return sorted(options, key=lambda c: (c.blocked is not None, c.net_cost, len(c.approvals)))


# ---------------------------------------------------------------- simulators
def _po_for(site: Site, gap: Shortfall):
    return next(l for l in site.po_lines.values() if l.material == gap.material)


def _wait(site: Site, gap: Shortfall) -> Consequences:
    po = _po_for(site, gap)
    offer = next(o for o in site.offers if o.supplier == po.supplier and o.material == gap.material)
    arrival = site.today + timedelta(days=offer.lead_days)
    days = max(0, (arrival - gap.needed_on).days)
    shifted = site.propagate_delay(gap.task_id, days)
    cost = site.delay_cost(shifted)
    return Consequences(
        option="wait_for_replacement",
        title=f"Esperar reposición de {po.supplier} (llega {arrival:%d/%m})",
        cash_out=cost, net_cost=cost, delay_days=days, shifted_tasks=tuple(shifted),
        budget_after={site.indirect_cost_code: site.budget_pct(site.indirect_cost_code, cost)},
        approvals=("residente",) if days else (), decide_by=None,
        notes=("Reposición sin costo de material: la cubre el proveedor.",),
    )


def _buy(site: Site, gap: Shortfall, supplier: str) -> Consequences:
    po = _po_for(site, gap)
    offer = next(o for o in site.offers if o.supplier == supplier and o.material == gap.material)
    arrival = site.today + timedelta(days=offer.lead_days)
    days = max(0, (arrival - gap.needed_on).days)
    shifted = site.propagate_delay(gap.task_id, days)
    cash = gap.gap * offer.unit_price + site.delay_cost(shifted)
    # The supplier still replaces the rejected tons, so the extra ton becomes
    # stock for the next level. The true cost is only the price premium.
    net = gap.gap * (offer.unit_price - po.unit_price) + site.delay_cost(shifted)
    approval = "gerente" if cash > LARGE_PURCHASE else "residente"
    return Consequences(
        option="buy_from_alternate",
        title=f"Comprar {gap.gap} t a {supplier} (llega {arrival:%d/%m})",
        cash_out=cash, net_cost=net, delay_days=days, shifted_tasks=tuple(shifted),
        budget_after={po.cost_code: site.budget_pct(po.cost_code, cash)},
        approvals=(approval,), decide_by=gap.needed_on - timedelta(days=offer.lead_days),
        notes=(f"Sobreprecio neto {net} MXN: la reposición del proveedor cubre el siguiente nivel.",),
    )


def _split(site: Site, gap: Shortfall) -> Consequences:
    task = site.tasks[gap.task_id]
    cost = task.split_extra_cost or D(0)
    return Consequences(
        option="split_task",
        title=f"Dividir '{task.name}' en dos etapas",
        cash_out=cost, net_cost=cost, delay_days=0, shifted_tasks=(),
        budget_after={site.indirect_cost_code: site.budget_pct(site.indirect_cost_code, cost)},
        approvals=task.split_requires, decide_by=gap.needed_on,
        notes=("Junta fría en la losa: requiere visto bueno estructural.",),
    )


def _use_rejected(site: Site, gap: Shortfall) -> Consequences:
    blocked = None
    if gap.material in site.open_ncr_material():
        blocked = ("Material con no conformidad abierta. No se puede usar en elementos "
                   "estructurales sin liberación del DRO, y usarlo anula el reclamo al proveedor.")
    return Consequences(
        option="use_rejected_material", title="Usar el material rechazado",
        cash_out=D(0), net_cost=D(0), delay_days=0, shifted_tasks=(), budget_after={},
        approvals=("DRO",), decide_by=None, blocked=blocked,
    )


_SIMULATORS = {
    "wait_for_replacement": _wait,
    "buy_from_alternate": _buy,
    "split_task": _split,
    "use_rejected_material": _use_rejected,
}
