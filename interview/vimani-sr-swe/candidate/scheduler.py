"""Inference Job Scheduler — starter code.

Implement the `Scheduler` class below. See PROBLEM.md for the full spec.

You may change anything in this file *except* the public names and signatures
used by the tests (the error classes, `Run`, `Schedule`, and the `Scheduler`
methods). Add helpers, classes, or modules as you see fit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class SchedulerError(ValueError):
    """Base class for all scheduler validation errors."""


class DuplicateJobError(SchedulerError):
    """A job with this id was already submitted."""


class UnknownJobError(SchedulerError, KeyError):
    """An operation referenced a job id that was never submitted."""


class UnknownDependencyError(SchedulerError):
    """A job depends on an id that does not exist (or is not active)."""


class CancelledDependencyError(SchedulerError):
    """A job was submitted with a dependency that is already cancelled."""


class CycleError(SchedulerError):
    """The dependency graph contains a cycle.

    `cycle` holds the ids of the jobs that form one cycle.
    """

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__("dependency cycle: " + " -> ".join(cycle + cycle[:1]))


@dataclass(frozen=True)
class Run:
    job_id: str
    worker: int
    start: int
    end: int


@dataclass(frozen=True)
class Schedule:
    runs: list[Run]  # in the order jobs were started
    makespan: int    # time at which the last job finishes (0 if no jobs)


class Scheduler:
    def __init__(self) -> None:
        pass

    def submit(
        self,
        job_id: str,
        priority: int,
        duration: int,
        depends_on: Iterable[str] = (),
    ) -> None:
        """Part 1. Register a job. Dependencies may be submitted later."""
        raise NotImplementedError

    def execution_order(self) -> list[str]:
        """Part 1. Return a valid order to run every active job on ONE worker."""
        raise NotImplementedError

    def simulate(self, workers: int) -> Schedule:
        """Part 2. Simulate running all active jobs on `workers` workers."""
        raise NotImplementedError

    def cancel(self, job_id: str) -> set[str]:
        """Part 3. Cancel a job and everything that (transitively) depends on it."""
        raise NotImplementedError
