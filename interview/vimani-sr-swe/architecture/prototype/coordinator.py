"""Coordinator: turns one field signal into actions for every affected party.

Flow for a delivery with defects:

  field report ──► [AI] perception ──► guardrail ──► supervisor confirms (1 tap)
                                                          │
                       deterministic commands ◄───────────┘
                       (receipt, NCR, invoice hold)
                                │ events
            ┌───────────────────┼────────────────────────┐
            ▼                   ▼                        ▼
     routing table      shortfall detection      supervisor playbook
     (who is affected)  + consequence engine     (what to do right now)
            │                   │
            ▼                   ▼
     [AI] drafts per     [AI] explains the
     audience + check    ranked options
            │
            ▼
     policy: auto-send or queue for approval
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ai import (
    LLM, ReceiptFacts, Suggestion, SuggestionLog, template_message,
    ungrounded_numbers, validate_receipt,
)
from decisions import ACTION_POLICY, OPTION_KINDS, Consequences, candidate_options, evaluate
from domain import Contact, Event, Shortfall, Site


@dataclass(frozen=True)
class OutboundMessage:
    audience: str
    to: Contact
    text: str
    status: str               # "sent" or "pending_approval:<role>"
    fallback_used: bool


@dataclass
class Outcome:
    events: list[Event] = field(default_factory=list)
    messages: list[OutboundMessage] = field(default_factory=list)
    shortfalls: list[Shortfall] = field(default_factory=list)
    options: list[Consequences] = field(default_factory=list)
    explanation: str | None = None
    next_steps: list[str] = field(default_factory=list)


# Which audiences each event concerns, and which policy governs the message.
ROUTING = {
    "GoodsRejected":     [("supplier", "message_supplier"), ("compras", "notify_internal")],
    "InvoiceHoldPlaced": [("cuentas_por_pagar", "notify_internal")],
    "Shortfall":         [("residente", "notify_internal"), ("foreman", "notify_internal")],
}


class Coordinator:
    def __init__(self, site: Site, llm: LLM, log: SuggestionLog | None = None) -> None:
        self.site = site
        self.llm = llm
        self.log = log or SuggestionLog()
        self._perception: Suggestion | None = None

    # ---------------------------------------------------------- step 1: perceive
    def read_field_report(self, text: str, photos: list[str], po_key: str) -> ReceiptFacts:
        line = self.site.po_lines[po_key]
        context = {"po": po_key, "material": line.material, "open_qty": line.open_qty}
        raw = self.llm.extract_receipt(text, photos, context)
        facts = validate_receipt(raw, context)
        self._perception = self.log.add(Suggestion("perception", raw, valid=True))
        return facts  # the app shows facts.reasons and asks for one-tap confirmation

    # ---------------------------------------------------------- step 2: act
    def confirm_receipt(self, facts: ReceiptFacts, defective: object = None,
                        photos: list[str] = ()) -> Outcome:
        """Supervisor confirmed (optionally correcting the defective count)."""
        rejected = facts.defective if defective is None else Decimal(str(defective))
        if self._perception is not None:
            self._perception.human_decision = (
                "accepted" if rejected == facts.defective else "edited")

        out = Outcome()
        out.events = self.site.record_receipt(
            facts.po, facts.delivered - rejected, rejected, facts.defect, list(photos))
        out.shortfalls = self.site.shortfalls()

        rejection = next((e for e in out.events if e.kind == "GoodsRejected"), None)
        hold = next((e for e in out.events if e.kind == "InvoiceHoldPlaced"), None)
        gap = out.shortfalls[0] if out.shortfalls else None

        if gap:
            out.options = candidate_options(self.site, gap)

        facts_by_audience = self._facts(rejection, hold, gap, out.options)
        for kind in [e.kind for e in out.events] + (["Shortfall"] if gap else []):
            for audience, action in ROUTING.get(kind, []):
                if audience in facts_by_audience:
                    out.messages.append(self._message(audience, action, facts_by_audience[audience]))

        if gap and out.options:
            out.explanation = self._explain(out.options)
        out.next_steps = self._playbook(rejection, gap, out.options)
        return out

    # ---------------------------------------------------------- what-if
    def what_if(self, question: str, gap: Shortfall) -> Consequences | str:
        """Answer "what happens if I…?" with computed consequences, never a guess."""
        parsed = self.llm.interpret_question(question, OPTION_KINDS)
        self.log.add(Suggestion("interpretation", parsed))
        if parsed.get("kind") not in OPTION_KINDS or parsed.get("confidence", 0) < 0.8:
            return ("No tengo forma de calcular esa opción. Opciones que sí puedo evaluar: "
                    "esperar reposición, comprar a otro proveedor, dividir la actividad.")
        return evaluate(self.site, gap, parsed["kind"])

    # ---------------------------------------------------------- helpers
    def _message(self, audience: str, action: str, facts: dict) -> OutboundMessage:
        try:
            draft = self.llm.draft_message(audience, facts)
            bad = ungrounded_numbers(draft, facts)
        except Exception:  # model unreachable (no signal on site) or timed out
            draft, bad = "", {"<llm unavailable>"}
        fallback = bool(bad)
        if fallback:  # the model invented or altered a number, or is down: don't send it
            draft = template_message(audience, facts)
        self.log.add(Suggestion("draft", draft, valid=not bad, fallback_used=fallback))
        policy = ACTION_POLICY[action]
        status = "sent" if policy == "auto" else f"pending_approval:{policy.split(':')[1]}"
        return OutboundMessage(audience, self.site.contacts[audience], draft, status, fallback)

    def _facts(self, rejection, hold, gap, options) -> dict[str, dict]:
        """Least privilege: each audience gets only the facts it needs.
        The supplier never sees our budget or that we're pricing alternatives."""
        facts: dict[str, dict] = {}
        if rejection:
            r = rejection.data
            line = self.site.po_lines[r["po"]]
            base = {"po": r["po"], "material": r["material"], "rejected": r["qty"],
                    "accepted": line.received, "defect": r["defect"], "ncr": r["ncr"]}
            facts["supplier"] = {"headline": f"Rechazo parcial {r['po']}", **base}
            facts["compras"] = {"headline": f"Rechazo parcial {r['po']}", **base,
                                "supplier": r["supplier"],
                                "gap": gap.gap if gap else 0,
                                "task": self.site.tasks[gap.task_id].name if gap else "-"}
        if hold:
            facts["cuentas_por_pagar"] = {"headline": "Retención de pago", "po": hold.data["po"],
                                          "hold": hold.data["amount"], "ncr": hold.data["ncr"]}
        if gap and options:
            best = options[0]
            task = self.site.tasks[gap.task_id]
            facts["residente"] = {"headline": "Faltante de material", "gap": gap.gap,
                                  "material": gap.material, "task": task.name,
                                  "recommended": best.title,
                                  "decide_by": f"{best.decide_by:%d/%m}" if best.decide_by else "hoy"}
            if task.foreman:
                facts["foreman"] = {"headline": "Posible cambio de programa", "task": task.name}
        return facts

    def _explain(self, options: list[Consequences]) -> str:
        best = options[0]
        wait = next(o for o in options if o.option == "wait_for_replacement")
        facts = {"recommended": best.title, "net_cost": best.net_cost, "best_delay": best.delay_days,
                 "wait_delay": wait.delay_days, "wait_cost": wait.net_cost}
        try:
            text = self.llm.explain(facts)
            bad = ungrounded_numbers(text, facts)
        except Exception:
            text, bad = "", {"<llm unavailable>"}
        self.log.add(Suggestion("explanation", text, valid=not bad, fallback_used=bool(bad)))
        return template_message("residente", {"headline": "Recomendación", **facts}) if bad else text

    def _playbook(self, rejection, gap, options) -> list[str]:
        """What the supervisor should do next, ordered by what expires first."""
        steps = []
        if rejection:
            r = rejection.data
            steps.append("Antes de que se vaya el chofer: anota el rechazo de "
                         f"{r['qty']} t en la remisión y pide su firma.")
            steps.append(f"Separa y etiqueta las {r['qty']} t con la {r['ncr']}. "
                         "No las mezcles con el material aceptado.")
        if gap and options:
            best = options[0]
            when = f"{best.decide_by:%d/%m}" if best.decide_by else "hoy"
            steps.append(f"Confirma con el residente la opción para "
                         f"'{self.site.tasks[gap.task_id].name}' antes del {when}.")
        return steps
