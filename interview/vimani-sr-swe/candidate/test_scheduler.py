"""Visible tests. Run with: python -m unittest -v"""

import unittest

from scheduler import (
    CancelledDependencyError,
    CycleError,
    DuplicateJobError,
    Run,
    Scheduler,
    UnknownDependencyError,
    UnknownJobError,
)


class Part1ExecutionOrder(unittest.TestCase):
    def test_respects_dependencies_submitted_out_of_order(self):
        s = Scheduler()
        s.submit("tokenize", priority=1, duration=2, depends_on=["fetch"])
        s.submit("fetch", priority=1, duration=1)
        self.assertEqual(s.execution_order(), ["fetch", "tokenize"])

    def test_higher_priority_first_then_submission_order(self):
        s = Scheduler()
        s.submit("low", priority=1, duration=1)
        s.submit("high", priority=9, duration=1)
        s.submit("mid_a", priority=5, duration=1)
        s.submit("mid_b", priority=5, duration=1)
        self.assertEqual(s.execution_order(), ["high", "mid_a", "mid_b", "low"])

    def test_duplicate_id_rejected(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=1)
        with self.assertRaises(DuplicateJobError):
            s.submit("a", priority=2, duration=1)

    def test_unknown_dependency(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=1, depends_on=["ghost"])
        with self.assertRaises(UnknownDependencyError):
            s.execution_order()

    def test_cycle_detected(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=1, depends_on=["c"])
        s.submit("b", priority=1, duration=1, depends_on=["a"])
        s.submit("c", priority=1, duration=1, depends_on=["b"])
        with self.assertRaises(CycleError) as ctx:
            s.execution_order()
        self.assertEqual(set(ctx.exception.cycle), {"a", "b", "c"})


class Part2Simulate(unittest.TestCase):
    def test_two_workers(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=3)
        s.submit("b", priority=5, duration=1)
        s.submit("c", priority=1, duration=2, depends_on=["b"])
        s.submit("d", priority=9, duration=2, depends_on=["a", "b"])
        schedule = s.simulate(workers=2)
        self.assertEqual(
            schedule.runs,
            [
                Run("b", worker=0, start=0, end=1),
                Run("a", worker=1, start=0, end=3),
                Run("c", worker=0, start=1, end=3),
                Run("d", worker=0, start=3, end=5),
            ],
        )
        self.assertEqual(schedule.makespan, 5)

    def test_empty(self):
        schedule = Scheduler().simulate(workers=3)
        self.assertEqual(schedule.runs, [])
        self.assertEqual(schedule.makespan, 0)


class Part3Cancel(unittest.TestCase):
    def test_cancel_cascades(self):
        s = Scheduler()
        s.submit("fetch", priority=1, duration=1)
        s.submit("embed", priority=1, duration=1, depends_on=["fetch"])
        s.submit("index", priority=1, duration=1, depends_on=["embed"])
        s.submit("other", priority=1, duration=1)
        self.assertEqual(s.cancel("embed"), {"embed", "index"})
        self.assertEqual(s.execution_order(), ["fetch", "other"])

    def test_cancel_unknown(self):
        with self.assertRaises(UnknownJobError):
            Scheduler().cancel("nope")

    def test_submit_on_cancelled_dependency(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=1)
        s.cancel("a")
        with self.assertRaises(CancelledDependencyError):
            s.submit("b", priority=1, duration=1, depends_on=["a"])


if __name__ == "__main__":
    unittest.main()
