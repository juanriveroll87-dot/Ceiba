"""Hidden edge-case tests — INTERVIEWER ONLY.

Run against a candidate's solution with:  ./check.sh path/to/their/scheduler.py
"""

import time
import unittest

from scheduler import (
    CancelledDependencyError,
    CycleError,
    Run,
    Scheduler,
    SchedulerError,
    UnknownDependencyError,
)


class Part1EdgeCases(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(Scheduler().execution_order(), [])

    def test_priority_never_overrides_dependencies(self):
        s = Scheduler()
        s.submit("base", priority=0, duration=1)
        s.submit("urgent", priority=100, duration=1, depends_on=["base"])
        s.submit("side", priority=50, duration=1)
        self.assertEqual(s.execution_order(), ["side", "base", "urgent"])

    def test_negative_priorities(self):
        s = Scheduler()
        s.submit("a", priority=-5, duration=1)
        s.submit("b", priority=-1, duration=1)
        self.assertEqual(s.execution_order(), ["b", "a"])

    def test_duplicate_entries_in_depends_on(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=1)
        s.submit("b", priority=1, duration=1, depends_on=["a", "a"])
        self.assertEqual(s.execution_order(), ["a", "b"])

    def test_invalid_duration(self):
        with self.assertRaises(SchedulerError):
            Scheduler().submit("a", priority=1, duration=0)

    def test_self_dependency_is_a_cycle(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=1, depends_on=["a"])
        with self.assertRaises(CycleError) as ctx:
            s.execution_order()
        self.assertEqual(ctx.exception.cycle, ["a"])

    def test_cycle_reports_only_cycle_members(self):
        # x -> y -> z -> y : x is upstream of the cycle, not part of it.
        s = Scheduler()
        s.submit("x", priority=1, duration=1, depends_on=["y"])
        s.submit("y", priority=1, duration=1, depends_on=["z"])
        s.submit("z", priority=1, duration=1, depends_on=["y"])
        with self.assertRaises(CycleError) as ctx:
            s.execution_order()
        self.assertEqual(set(ctx.exception.cycle), {"y", "z"})

    def test_does_not_mutate_state(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=1)
        s.submit("b", priority=2, duration=1, depends_on=["a"])
        first = s.execution_order()
        self.assertEqual(s.execution_order(), first)
        self.assertEqual(s.simulate(workers=2).runs, s.simulate(workers=2).runs)


class Part2EdgeCases(unittest.TestCase):
    def test_simultaneous_completions_release_together(self):
        s = Scheduler()
        s.submit("x", priority=1, duration=2)
        s.submit("y", priority=1, duration=2)
        s.submit("z", priority=1, duration=1, depends_on=["x"])
        s.submit("w", priority=10, duration=1, depends_on=["y"])
        runs = s.simulate(workers=2).runs
        # Both x and y finish at t=2; w (higher priority) must get worker 0.
        self.assertEqual(runs[2:], [Run("w", 0, 2, 3), Run("z", 1, 2, 3)])

    def test_more_workers_than_jobs(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=4)
        s.submit("b", priority=1, duration=2)
        schedule = s.simulate(workers=10)
        self.assertEqual(schedule.runs, [Run("a", 0, 0, 4), Run("b", 1, 0, 2)])
        self.assertEqual(schedule.makespan, 4)

    def test_idle_gap_waiting_on_dependency(self):
        s = Scheduler()
        s.submit("long", priority=1, duration=5)
        s.submit("after", priority=1, duration=1, depends_on=["long"])
        schedule = s.simulate(workers=3)
        self.assertEqual(schedule.runs[-1], Run("after", 0, 5, 6))
        self.assertEqual(schedule.makespan, 6)

    def test_single_worker_matches_execution_order(self):
        s = Scheduler()
        for i in range(20):
            deps = [f"j{i - 3}"] if i >= 3 else []
            s.submit(f"j{i}", priority=i % 4, duration=1 + i % 3, depends_on=deps)
        self.assertEqual(
            [r.job_id for r in s.simulate(workers=1).runs], s.execution_order()
        )

    def test_invalid_workers(self):
        with self.assertRaises(SchedulerError):
            Scheduler().simulate(workers=0)

    def test_validation_applies_to_simulate(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=1, depends_on=["missing"])
        with self.assertRaises(UnknownDependencyError):
            s.simulate(workers=2)


class Part3EdgeCases(unittest.TestCase):
    def test_diamond_cascade(self):
        s = Scheduler()
        s.submit("root", priority=1, duration=1)
        s.submit("l", priority=1, duration=1, depends_on=["root"])
        s.submit("r", priority=1, duration=1, depends_on=["root"])
        s.submit("join", priority=1, duration=1, depends_on=["l", "r"])
        self.assertEqual(s.cancel("root"), {"root", "l", "r", "join"})
        self.assertEqual(s.execution_order(), [])

    def test_cancel_is_idempotent(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=1)
        s.submit("b", priority=1, duration=1, depends_on=["a"])
        self.assertEqual(s.cancel("b"), {"b"})
        self.assertEqual(s.cancel("a"), {"a"})
        self.assertEqual(s.cancel("a"), set())

    def test_cancel_cascades_to_dependents_submitted_before_dependency(self):
        s = Scheduler()
        s.submit("child", priority=1, duration=1, depends_on=["parent"])
        s.submit("parent", priority=1, duration=1)
        self.assertEqual(s.cancel("parent"), {"parent", "child"})

    def test_cancelling_a_cycle_member_unblocks_planning(self):
        s = Scheduler()
        s.submit("ok", priority=1, duration=1)
        s.submit("a", priority=1, duration=1, depends_on=["b"])
        s.submit("b", priority=1, duration=1, depends_on=["a"])
        self.assertEqual(s.cancel("a"), {"a", "b"})
        self.assertEqual(s.execution_order(), ["ok"])

    def test_cancelled_dependency_check_is_on_submit(self):
        s = Scheduler()
        s.submit("a", priority=1, duration=1)
        s.cancel("a")
        with self.assertRaises(CancelledDependencyError):
            s.submit("b", priority=1, duration=1, depends_on=["a"])


class Scale(unittest.TestCase):
    """Catches O(n^2) algorithms and recursion-depth blowups."""

    N = 50_000

    def test_long_chain(self):
        s = Scheduler()
        s.submit("j0", priority=0, duration=1)
        for i in range(1, self.N):
            s.submit(f"j{i}", priority=0, duration=1, depends_on=[f"j{i - 1}"])
        started = time.perf_counter()
        schedule = s.simulate(workers=4)
        self.assertEqual(schedule.makespan, self.N)
        self.assertEqual(len(s.cancel("j1")), self.N - 1)
        self.assertLess(time.perf_counter() - started, 5.0)

    def test_wide_fan_out(self):
        s = Scheduler()
        s.submit("root", priority=0, duration=1)
        for i in range(self.N):
            s.submit(f"leaf{i}", priority=i % 7, duration=1, depends_on=["root"])
        started = time.perf_counter()
        self.assertEqual(len(s.execution_order()), self.N + 1)
        self.assertLess(time.perf_counter() - started, 5.0)


if __name__ == "__main__":
    unittest.main()
