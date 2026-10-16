"""The AI layer: an LLM behind a narrow port, wrapped in guardrails.

The LLM does four jobs, and only these four:
  1. Perception:     unstructured field input (voice, photos, text) -> structured facts
  2. Interpretation: a supervisor's free-text question -> one known option kind
  3. Drafting:       facts -> a message written for a specific audience
  4. Explanation:    computed consequences -> plain-language advice

It never computes a number that matters, and it never calls a command directly.
Every output is validated, and every output is logged so acceptance rate can
be measured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Protocol

MODEL_VERSION = "fake-llm-2026-10"
CONFIRM_BELOW = 0.90  # perception confidence under this -> ask the supervisor


class LLM(Protocol):
    def extract_receipt(self, text: str, photos: list[str], po_context: dict) -> dict: ...
    def interpret_question(self, text: str, allowed_kinds: tuple[str, ...]) -> dict: ...
    def draft_message(self, audience: str, facts: dict) -> str: ...
    def explain(self, facts: dict) -> str: ...


# ------------------------------------------------------------------ logging
@dataclass
class Suggestion:
    task: str
    output: object
    model: str = MODEL_VERSION
    valid: bool = True
    fallback_used: bool = False
    human_decision: str | None = None  # "accepted" / "edited" / "rejected"


@dataclass
class SuggestionLog:
    items: list[Suggestion] = field(default_factory=list)

    def add(self, s: Suggestion) -> Suggestion:
        self.items.append(s)
        return s

    def acceptance_rate(self, task: str) -> float | None:
        decided = [s for s in self.items if s.task == task and s.human_decision]
        if not decided:
            return None
        return sum(s.human_decision == "accepted" for s in decided) / len(decided)


# ------------------------------------------------------------------ guardrails
@dataclass(frozen=True)
class ReceiptFacts:
    po: str
    delivered: Decimal
    defective: Decimal
    defect: str
    confidence: float
    needs_confirmation: bool
    reasons: tuple[str, ...]


def validate_receipt(raw: dict, po_context: dict) -> ReceiptFacts:
    """Check the model's reading against the purchase order before anyone acts on it."""
    reasons = []
    try:
        delivered = Decimal(str(raw["delivered"]))
        defective = Decimal(str(raw.get("defective", 0)))
        confidence = float(raw.get("confidence", 0.0))  # missing confidence = no confidence
    except (KeyError, InvalidOperation, ValueError, TypeError):
        raise ValueError(f"unusable extraction: {raw!r}") from None

    if raw.get("po") != po_context["po"]:
        raise ValueError(f"model read PO {raw.get('po')!r}, expected {po_context['po']!r}")
    if raw.get("material") != po_context["material"]:
        reasons.append("el material no coincide con la orden de compra")
    if delivered > po_context["open_qty"]:
        reasons.append(f"llegó más de lo pendiente ({po_context['open_qty']})")
    if not 0 <= defective <= delivered:
        reasons.append("cantidad defectuosa fuera de rango")
    if raw.get("estimated"):
        reasons.append("la cantidad defectuosa es una estimación")
    if confidence < CONFIRM_BELOW:
        reasons.append(f"confianza {confidence:.2f}")

    return ReceiptFacts(po_context["po"], delivered, defective, str(raw.get("defect", "")),
                        confidence, bool(reasons), tuple(reasons))


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUMBER.findall(text):
        try:
            out.add(str(Decimal(m.replace(",", "")).normalize()))
        except InvalidOperation:
            pass
    return out


def _flatten(value) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten(v) for v in value)
    return str(value)


def ungrounded_numbers(text: str, facts: dict) -> set[str]:
    """Numbers in an AI-written text that don't come from the facts it was given."""
    return _numbers(text) - _numbers(_flatten(facts))


def template_message(audience: str, facts: dict) -> str:
    """Deterministic fallback: plain, correct, and boring. Works offline."""
    lines = [f"[{audience}] {facts['headline']}"]
    lines += [f"- {k}: {v}" for k, v in facts.items() if k not in ("headline",)]
    return "\n".join(lines)


# ------------------------------------------------------------------ fake model
class FakeLLM:
    """Stands in for a real model so the prototype is deterministic and offline.

    A real implementation would call a hosted model with tool/JSON schemas;
    the guardrails above don't change.
    """

    def extract_receipt(self, text, photos, po_context):
        # "Llegaron las 40 toneladas de varilla de la PO-1182, como 3 vienen dobladas y oxidadas"
        return {"po": "PO-1182/1", "material": po_context["material"], "delivered": 40,
                "defective": 3, "defect": "varilla doblada y con oxidación", "estimated": True,
                "confidence": 0.78}

    def interpret_question(self, text, allowed_kinds):
        lowered = text.lower()
        if "dañad" in lowered or "rechazad" in lowered or "defectu" in lowered:
            return {"kind": "use_rejected_material", "confidence": 0.93}
        if "esper" in lowered:
            return {"kind": "wait_for_replacement", "confidence": 0.91}
        return {"kind": "unknown", "confidence": 0.2}

    def draft_message(self, audience, facts):
        f = facts
        if audience == "supplier":
            return (f"Buen día. En la entrega de la {f['po']} recibimos {f['accepted']} t y "
                    f"rechazamos {f['rejected']} t de {f['material']} por {f['defect']} "
                    f"({f['ncr']}, fotos adjuntas). Solicitamos reposición de {f['rejected']} t "
                    f"y confirmar fecha de entrega. La factura correspondiente queda en espera.")
        if audience == "compras":
            return (f"{f['ncr']}: {f['supplier']} entregó {f['rejected']} t defectuosas en la "
                    f"{f['po']}. Hay un faltante de {f['gap']} t para '{f['task']}'. "
                    f"Mensaje al proveedor listo para tu aprobación.")
        if audience == "cuentas_por_pagar":
            return (f"Retener {f['hold']} MXN de la factura de la {f['po']} hasta cerrar "
                    f"la {f['ncr']}.")
        if audience == "residente":
            return (f"Faltan {f['gap']} t de {f['material']} para '{f['task']}'. "
                    f"Recomendado: {f['recommended']}. Decide antes del {f['decide_by']}.")
        if audience == "foreman":
            return f"Atención: '{f['task']}' podría moverse. Te confirmamos hoy."
        return template_message(audience, facts)

    def explain(self, facts):
        return (f"Te recomiendo: {facts['recommended']}. Cuesta {facts['net_cost']} MXN netos y "
                f"retrasa el programa {facts['best_delay']} días. Esperar al proveedor retrasa {facts['wait_delay']} días "
                f"y cuesta {facts['wait_cost']} MXN.")
