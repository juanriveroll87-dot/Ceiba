"""Visible tests. Run with: python -m unittest -v"""

import unittest
from decimal import Decimal as D

from budget import (
    Alert,
    Catalog,
    DuplicateCodeError,
    DuplicateTransactionError,
    LevelError,
    NotALeafError,
    Project,
    UnknownCodeError,
)


def make_project() -> Project:
    catalog = Catalog(common_depth=2)
    catalog.add("01", "Preliminares")
    catalog.add("01.01", "Permisos")
    catalog.add("03", "Estructura")
    catalog.add("03.01", "Cimentación")
    catalog.add("03.02", "Concreto")
    obra = Project("Torre Norte", catalog)
    obra.add_code("03.02.010", "Columnas")
    obra.add_code("03.02.020", "Losas")
    return obra


class Part1Catalog(unittest.TestCase):
    def test_project_codes_hang_off_template(self):
        obra = make_project()
        self.assertEqual(obra.report("03.02.010").name, "Columnas")
        self.assertEqual(obra.report("03").name, "Estructura")

    def test_parent_must_exist(self):
        with self.assertRaises(UnknownCodeError):
            make_project().add_code("05.01.001", "Huérfano")

    def test_duplicate_code(self):
        with self.assertRaises(DuplicateCodeError):
            make_project().add_code("03.02.010", "Otra vez")

    def test_levels_are_enforced(self):
        catalog = Catalog(common_depth=2)
        catalog.add("03", "Estructura")
        catalog.add("03.02", "Concreto")
        with self.assertRaises(LevelError):
            catalog.add("03.02.010", "Too deep for the template")
        with self.assertRaises(LevelError):
            Project("P", catalog).add_code("04", "Projects can't add level 1")


class Part2Rollups(unittest.TestCase):
    def test_example_from_problem(self):
        obra = make_project()
        obra.set_budget("03.02.010", "100000.00")
        self.assertTrue(obra.post("REQ-881", "03.02.010", "commitment", "60000.00"))
        self.assertTrue(obra.post("INV-112", "03.02.010", "actual", "45000.50"))
        line = obra.report("03")
        self.assertEqual(line.budget, D("100000.00"))
        self.assertEqual(line.committed, D("60000.00"))
        self.assertEqual(line.actual, D("45000.50"))
        self.assertEqual(line.exposure, D("105000.50"))
        self.assertEqual(line.remaining, D("-5000.50"))

    def test_rollup_across_siblings(self):
        obra = make_project()
        obra.set_budget("03.02.010", "100")
        obra.set_budget("03.02.020", "250")
        obra.set_budget("03.01", "50")
        self.assertEqual(obra.report("03.02").budget, D("350"))
        self.assertEqual(obra.report("03").budget, D("400"))
        self.assertEqual(obra.report("01").budget, D("0"))

    def test_only_leaves_take_money(self):
        obra = make_project()
        with self.assertRaises(NotALeafError):
            obra.post("T1", "03.02", "actual", "10")

    def test_replay_is_a_no_op(self):
        obra = make_project()
        self.assertTrue(obra.post("INV-1", "03.01", "actual", "500"))
        self.assertFalse(obra.post("INV-1", "03.01", "actual", "500"))
        self.assertEqual(obra.report("03.01").actual, D("500"))

    def test_conflicting_replay(self):
        obra = make_project()
        obra.post("INV-1", "03.01", "actual", "500")
        with self.assertRaises(DuplicateTransactionError):
            obra.post("INV-1", "03.01", "actual", "5000")


class Part3Alerts(unittest.TestCase):
    def test_example_from_problem(self):
        obra = make_project()
        obra.set_budget("03.02.010", "100000.00")
        obra.post("REQ-881", "03.02.010", "commitment", "60000.00")
        obra.post("INV-112", "03.02.010", "actual", "45000.50")
        self.assertEqual(
            obra.alerts(threshold="0.05", limit=10),
            [Alert("03.02.010", D("100000.00"), D("105000.50"), D("5000.50"))],
        )

    def test_sorted_by_overrun(self):
        obra = make_project()
        obra.set_budget("03.02.010", "100")
        obra.set_budget("03.02.020", "100")
        obra.post("A", "03.02.010", "actual", "150")
        obra.post("B", "03.02.020", "actual", "300")
        self.assertEqual(
            [a.code for a in obra.alerts()], ["03.02.020", "03.02.010"]
        )


if __name__ == "__main__":
    unittest.main()
