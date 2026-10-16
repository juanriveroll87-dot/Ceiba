"""Guardrail tests: python -m unittest -v

These test the *architecture's* promises, not the model's quality:
the model can be wrong, slow or offline, and the system stays correct.
"""

import unittest
from decimal import Decimal as D

from ai import FakeLLM, SuggestionLog, validate_receipt
from coordinator import Coordinator
from domain import DomainError
from scenario import torre_norte

REPORT = "Llegaron las 40 toneladas de varilla de la PO-1182, como 3 vienen dobladas"


def run(llm=None):
    site = torre_norte()
    coord = Coordinator(site, llm or FakeLLM(), SuggestionLog())
    facts = coord.read_field_report(REPORT, [], "PO-1182/1")
    return site, coord, coord.confirm_receipt(facts, defective=3)


class LyingLLM(FakeLLM):
    """Changes a quantity in the supplier message: the quiet, expensive kind of error."""

    def draft_message(self, audience, facts):
        text = super().draft_message(audience, facts)
        return text.replace("rechazamos 3 t", "rechazamos 5 t")


class OfflineLLM(FakeLLM):
    def draft_message(self, audience, facts):
        raise TimeoutError("no signal")

    def explain(self, facts):
        raise TimeoutError("no signal")


class Perception(unittest.TestCase):
    CONTEXT = {"po": "PO-1182/1", "material": "varilla 3/8", "open_qty": D(40)}

    def test_estimate_requires_confirmation(self):
        facts = validate_receipt({"po": "PO-1182/1", "material": "varilla 3/8", "delivered": 40,
                                  "defective": 3, "estimated": True, "confidence": 0.95},
                                 self.CONTEXT)
        self.assertTrue(facts.needs_confirmation)

    def test_wrong_po_is_rejected_outright(self):
        with self.assertRaises(ValueError):
            validate_receipt({"po": "PO-9999/1", "delivered": 40, "confidence": 0.99},
                             self.CONTEXT)

    def test_missing_confidence_means_no_confidence(self):
        facts = validate_receipt({"po": "PO-1182/1", "material": "varilla 3/8",
                                  "delivered": 40}, self.CONTEXT)
        self.assertTrue(facts.needs_confirmation)

    def test_over_delivery_flagged(self):
        facts = validate_receipt({"po": "PO-1182/1", "material": "varilla 3/8", "delivered": 45,
                                  "confidence": 0.99}, self.CONTEXT)
        self.assertTrue(facts.needs_confirmation)

    def test_supervisor_correction_is_logged_as_edit(self):
        site = torre_norte()
        log = SuggestionLog()
        coord = Coordinator(site, FakeLLM(), log)
        coord.confirm_receipt(coord.read_field_report(REPORT, [], "PO-1182/1"), defective=4)
        self.assertEqual(log.acceptance_rate("perception"), 0.0)
        self.assertEqual(site.inventory["varilla 3/8"], D(36))


class SystemOfRecord(unittest.TestCase):
    def test_partial_rejection(self):
        site, _, out = run()
        self.assertEqual(site.inventory["varilla 3/8"], D(37))
        self.assertEqual(site.po_lines["PO-1182/1"].open_qty, D(3))
        hold = next(e for e in out.events if e.kind == "InvoiceHoldPlaced")
        self.assertEqual(hold.data["amount"], D(64500))

    def test_invalid_receipt_changes_nothing(self):
        site = torre_norte()
        with self.assertRaises(DomainError):
            site.record_receipt("PO-1182/1", D(39), D(3), "x", [])
        self.assertEqual(site.inventory["varilla 3/8"], D(0))
        self.assertEqual(site.events, [])


class Coordination(unittest.TestCase):
    def test_everyone_affected_is_reached(self):
        _, _, out = run()
        self.assertEqual({m.audience for m in out.messages},
                         {"supplier", "compras", "cuentas_por_pagar", "residente", "foreman"})

    def test_external_messages_wait_for_approval(self):
        _, _, out = run()
        supplier = next(m for m in out.messages if m.audience == "supplier")
        self.assertEqual(supplier.status, "pending_approval:compras")
        internal = [m for m in out.messages if not m.to.external]
        self.assertTrue(all(m.status == "sent" for m in internal))

    def test_supplier_never_sees_budget_or_alternatives(self):
        _, _, out = run()
        supplier = next(m for m in out.messages if m.audience == "supplier")
        for secret in ("Ferretera", "03.02.010", "25370", "presupuesto"):
            self.assertNotIn(secret, supplier.text)

    def test_altered_number_triggers_template_fallback(self):
        _, _, out = run(LyingLLM())
        supplier = next(m for m in out.messages if m.audience == "supplier")
        self.assertTrue(supplier.fallback_used)
        self.assertNotIn("5 t", supplier.text)
        self.assertIn("rejected: 3", supplier.text)

    def test_offline_still_coordinates(self):
        _, _, out = run(OfflineLLM())
        self.assertEqual(len(out.messages), 5)
        self.assertTrue(all(m.fallback_used for m in out.messages))
        self.assertIn("3870", out.explanation)


class Anticipation(unittest.TestCase):
    def test_shortfall_detected(self):
        _, _, out = run()
        [gap] = out.shortfalls
        self.assertEqual((gap.task_id, gap.gap), ("ARM-N4", D(1)))

    def test_options_ranked_by_net_cost(self):
        _, _, out = run()
        self.assertEqual([o.option for o in out.options],
                         ["buy_from_alternate", "split_task", "wait_for_replacement"])
        wait = out.options[-1]
        self.assertEqual((wait.delay_days, wait.net_cost), (2, D(78000)))
        self.assertEqual(wait.shifted_tasks, ("ARM-N4", "COL-N4", "CIM-N5"))

    def test_next_steps_start_with_what_expires_first(self):
        _, _, out = run()
        self.assertIn("chofer", out.next_steps[0])

    def test_unsafe_decision_is_blocked_with_reason(self):
        _, coord, out = run()
        answer = coord.what_if("¿Y si usamos las varillas dañadas?", out.shortfalls[0])
        self.assertIsNotNone(answer.blocked)
        self.assertIn("DRO", answer.blocked)

    def test_unknown_decision_is_not_guessed(self):
        _, coord, out = run()
        answer = coord.what_if("¿Y si cambiamos de diseño estructural?", out.shortfalls[0])
        self.assertIsInstance(answer, str)


if __name__ == "__main__":
    unittest.main()
