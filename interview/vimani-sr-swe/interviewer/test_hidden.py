"""Hidden edge-case tests — INTERVIEWER ONLY.

Run against a candidate's solution with:  ./check.sh path/to/their/budget.py
Each test's docstring names the "quiet" mistake it catches.
"""

import time
import unittest
from decimal import Decimal as D

from budget import (
    BudgetError,
    Catalog,
    CodeInUseError,
    InvalidAmountError,
    InvalidCodeError,
    LevelError,
    NotALeafError,
    Project,
    UnknownCodeError,
)


def make_project(common_depth: int = 2) -> Project:
    catalog = Catalog(common_depth=common_depth)
    catalog.add("01", "Preliminares")
    catalog.add("01.01", "Permisos")
    catalog.add("03", "Estructura")
    catalog.add("03.01", "Cimentación")
    catalog.add("03.02", "Concreto")
    obra = Project("Torre Norte", catalog)
    obra.add_code("03.02.010", "Columnas")
    obra.add_code("03.02.020", "Losas")
    return obra


class Part1EdgeCases(unittest.TestCase):
    def test_malformed_codes(self):
        """Loose parsing lets '03..1' or '03.' into the spine of the data model."""
        catalog = Catalog(common_depth=2)
        for bad in ["", ".", "03.", ".03", "03..1", "03.0 1", "03/01"]:
            with self.subTest(code=bad), self.assertRaises(InvalidCodeError):
                catalog.add(bad, "x")

    def test_template_is_snapshotted(self):
        """Projects that share mutable template state change under a running project."""
        catalog = Catalog(common_depth=2)
        catalog.add("03", "Estructura")
        obra = Project("A", catalog)
        catalog.add("04", "Instalaciones")
        with self.assertRaises(UnknownCodeError):
            obra.report("04")

    def test_projects_are_independent(self):
        """Project-specific codes leak into other projects or into the template."""
        catalog = Catalog(common_depth=1)
        catalog.add("03", "Estructura")
        a, b = Project("A", catalog), Project("B", catalog)
        a.add_code("03.01", "Solo en A")
        b.add_code("03.01", "Solo en B")  # must not be a DuplicateCodeError
        a.set_budget("03.01", "10")
        self.assertEqual(b.report("03").budget, D("0"))

    def test_project_cannot_add_template_level_codes(self):
        with self.assertRaises(LevelError):
            make_project().add_code("03.03", "Acero")

    def test_codes_compare_as_codes_not_prefixes(self):
        """Prefix matching ('03.1' startswith '03.1') double counts '03.10' under '03.1'."""
        catalog = Catalog(common_depth=1)
        catalog.add("03", "Estructura")
        obra = Project("P", catalog)
        obra.add_code("03.1", "Uno")
        obra.add_code("03.10", "Diez")
        obra.set_budget("03.1", "1")
        obra.set_budget("03.10", "10")
        self.assertEqual(obra.report("03.1").budget, D("1"))
        self.assertEqual(obra.report("03").budget, D("11"))


class Part2EdgeCases(unittest.TestCase):
    def test_money_is_exact(self):
        """Floats: ten postings of 0.10 must equal exactly 1.00."""
        obra = make_project()
        for i in range(10):
            obra.post(f"T{i}", "03.01", "actual", "0.10")
        self.assertEqual(obra.report("03").actual, D("1.00"))

    def test_invalid_amounts(self):
        """Decimal('NaN') parses fine and silently poisons every total above it."""
        obra = make_project()
        for i, bad in enumerate(["abc", "", "NaN", "Infinity", None]):
            with self.subTest(amount=bad), self.assertRaises(InvalidAmountError):
                obra.post(f"T{i}", "03.01", "actual", bad)

    def test_negative_budget_rejected_but_negative_postings_allowed(self):
        obra = make_project()
        with self.assertRaises(InvalidAmountError):
            obra.set_budget("03.01", "-1")
        obra.post("PO-1", "03.01", "commitment", "1000")
        obra.post("PO-1-REL", "03.01", "commitment", "-1000")
        self.assertEqual(obra.report("03").committed, D("0"))

    def test_set_budget_replaces(self):
        """Budget accumulates instead of replacing, so rollups drift."""
        obra = make_project()
        obra.set_budget("03.01", "100")
        obra.set_budget("03.01", "80")
        self.assertEqual(obra.report("03").budget, D("80"))

    def test_replay_does_not_double_count_rollups(self):
        obra = make_project()
        obra.post("X", "03.02.010", "commitment", "100")
        obra.post("X", "03.02.010", "commitment", "100")
        self.assertEqual(obra.report("03").committed, D("100"))

    def test_replay_with_equivalent_amount_is_a_no_op(self):
        """'100' and '100.00' are the same money."""
        obra = make_project()
        obra.post("X", "03.01", "actual", "100")
        self.assertFalse(obra.post("X", "03.01", "actual", "100.00"))

    def test_conflict_on_different_code_or_kind(self):
        obra = make_project()
        obra.post("X", "03.01", "actual", "100")
        for code, kind in [("01.01", "actual"), ("03.01", "commitment")]:
            with self.subTest(code=code, kind=kind), self.assertRaises(BudgetError):
                obra.post("X", code, kind, "100")
        self.assertEqual(obra.report("03.01").actual, D("100"))

    def test_rejected_post_has_no_side_effects(self):
        """A failed write must not half-apply or burn the txn id."""
        obra = make_project()
        with self.assertRaises(NotALeafError):
            obra.post("X", "03", "actual", "100")
        with self.assertRaises(InvalidAmountError):
            obra.post("Y", "03.01", "actual", "oops")
        self.assertTrue(obra.post("X", "03.01", "actual", "100"))
        self.assertTrue(obra.post("Y", "03.01", "actual", "1"))
        self.assertEqual(obra.report("03").actual, D("101"))

    def test_invalid_kind(self):
        with self.assertRaises(BudgetError):
            make_project().post("X", "03.01", "spent", "1")

    def test_unknown_codes(self):
        obra = make_project()
        with self.assertRaises(UnknownCodeError):
            obra.report("99")
        with self.assertRaises(UnknownCodeError):
            obra.post("X", "99.99.999", "actual", "1")

    def test_cannot_split_a_code_that_has_money(self):
        obra = make_project()
        obra.post("X", "03.01", "actual", "1")
        with self.assertRaises(CodeInUseError):
            obra.add_code("03.01.001", "Zapatas")

    def test_template_leaf_without_children_takes_money(self):
        obra = make_project()
        obra.set_budget("01.01", "5")
        self.assertEqual(obra.report("01").budget, D("5"))


class Part3EdgeCases(unittest.TestCase):
    def test_unbudgeted_spend_is_flagged(self):
        """Division by zero, or skipping zero-budget codes, hides real spend."""
        obra = make_project()
        obra.post("X", "01.01", "actual", "0.01")
        alerts = obra.alerts()
        self.assertEqual([a.code for a in alerts], ["01.01"])
        self.assertEqual(alerts[0].overrun, D("0.01"))

    def test_exactly_at_threshold_is_not_flagged(self):
        obra = make_project()
        obra.set_budget("03.01", "100")
        obra.post("X", "03.01", "actual", "105")
        self.assertEqual(obra.alerts(threshold="0.05"), [])
        obra.post("Y", "03.01", "actual", "0.01")
        self.assertEqual(len(obra.alerts(threshold="0.05")), 1)

    def test_commitments_count_before_invoices_arrive(self):
        """The whole point: warn on committed money, not only on paid money."""
        obra = make_project()
        obra.set_budget("03.01", "100")
        obra.post("PO", "03.01", "commitment", "120")
        self.assertEqual([a.code for a in obra.alerts()], ["03.01"])

    def test_depth_uses_rollups(self):
        """Parent-level alerts net savings against overruns (not max of children)."""
        obra = make_project()
        obra.set_budget("03.02.010", "100")
        obra.set_budget("03.02.020", "100")
        obra.post("A", "03.02.010", "actual", "50")
        obra.post("B", "03.02.020", "actual", "160")
        self.assertEqual([a.code for a in obra.alerts()], ["03.02.020"])
        by_level = obra.alerts(depth=2)
        self.assertEqual([a.code for a in by_level], ["03.02"])
        self.assertEqual(by_level[0].overrun, D("10"))
        self.assertEqual([a.code for a in obra.alerts(depth=1)], ["03"])
        self.assertEqual(obra.alerts(threshold="0.05", depth=1), [])

    def test_tie_break_by_code(self):
        obra = make_project()
        obra.post("A", "03.02.020", "actual", "10")
        obra.post("B", "03.01", "actual", "10")
        obra.post("C", "01.01", "actual", "10")
        self.assertEqual(
            [a.code for a in obra.alerts()], ["01.01", "03.01", "03.02.020"]
        )

    def test_limit(self):
        obra = make_project()
        for i, code in enumerate(["01.01", "03.01", "03.02.010", "03.02.020"]):
            obra.post(f"T{i}", code, "actual", str(i + 1))
        self.assertEqual(
            [a.code for a in obra.alerts(limit=2)], ["03.02.020", "03.02.010"]
        )
        self.assertEqual(obra.alerts(limit=0), [])

    def test_negative_threshold(self):
        with self.assertRaises(InvalidAmountError):
            make_project().alerts(threshold="-0.1")

    def test_credits_can_clear_an_alert(self):
        obra = make_project()
        obra.set_budget("03.01", "100")
        obra.post("INV", "03.01", "actual", "150")
        obra.post("CN", "03.01", "actual", "-60")
        self.assertEqual(obra.alerts(), [])


class Scale(unittest.TestCase):
    """~4k codes, 200k postings, 20k reports. Catches O(postings) per report."""

    def test_realistic_project_size(self):
        catalog = Catalog(common_depth=2)
        for a in range(20):
            catalog.add(f"{a:02d}", f"Capítulo {a}")
            for b in range(10):
                catalog.add(f"{a:02d}.{b:02d}", f"Partida {a}.{b}")
        obra = Project("Grande", catalog)
        leaves = []
        for a in range(20):
            for b in range(10):
                for c in range(20):
                    code = f"{a:02d}.{b:02d}.{c:03d}"
                    obra.add_code(code, "Concepto")
                    leaves.append(code)

        started = time.perf_counter()
        for i in range(200_000):
            obra.post(f"T{i}", leaves[i % len(leaves)], "actual", "1.25")
        for i in range(20_000):
            obra.report(f"{i % 20:02d}")
        obra.alerts(limit=50)
        elapsed = time.perf_counter() - started

        total = sum((obra.report(f"{a:02d}").actual for a in range(20)), D("0"))
        self.assertEqual(total, D("250000.00"))
        self.assertLess(elapsed, 10.0)


if __name__ == "__main__":
    unittest.main()
