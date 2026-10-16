"""Reference solution — INTERVIEWER ONLY. Do not share with candidates.

Design notes
------------
* Jobs are stored in a dict (O(1) lookup) plus a submission counter used as a
  deterministic tie-breaker.
* `_dependents` is the reverse adjacency list, maintained at submit time so
  that cancellation cascades in O(V + E) without rescanning every job.
* Planning is Kahn's algorithm with a priority queue instead of a FIFO queue.
* `execution_order()` is just `simulate(workers=1)` — one code path, one set of
  ordering rules.
* Simulation is event-driven: a heap of running jobs keyed by end time, a heap
  of ready jobs keyed by (-priority, submission order), and a heap of free
  worker ids. Time jumps from event to event, never ticks.

Complexity: O((V + E) log V) time, O(V + E) space.
"""

from __future__ import annotations

import heapq
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable


class SchedulerError(ValueError):
    """Base class for all scheduler validation errors."""


class DuplicateJobError(SchedulerError):
    pass


class UnknownJobError(SchedulerError, KeyError):
    pass


class UnknownDependencyError(SchedulerError):
    pass


class CancelledDependencyError(SchedulerError):
    pass


class CycleError(SchedulerError):
    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__("dependency cycle: " + " -> ".join(cycle + cycle[:1]))


@dataclass(frozen=True)
class Job:
    id: str
    priority: int
    duration: int
    depends_on: tuple[str, ...]
    seq: int  # submission order, used for deterministic tie-breaking


@dataclass(frozen=True)
class Run:
    job_id: str
    worker: int
    start: int
    end: int


@dataclass(frozen=True)
class Schedule:
    runs: list[Run]
    makespan: int


class Scheduler:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._dependents: dict[str, list[str]] = defaultdict(list)
        self._cancelled: set[str] = set()

    # ----------------------------------------------------------------- submit
    def submit(
        self,
        job_id: str,
        priority: int,
        duration: int,
        depends_on: Iterable[str] = (),
    ) -> None:
        if job_id in self._jobs:
            raise DuplicateJobError(f"job {job_id!r} already submitted")
        if duration < 1:
            raise SchedulerError(f"job {job_id!r}: duration must be >= 1")

        deps = tuple(dict.fromkeys(depends_on))  # de-dupe, keep order
        cancelled = [d for d in deps if d in self._cancelled]
        if cancelled:
            raise CancelledDependencyError(
                f"job {job_id!r} depends on cancelled job(s) {cancelled}"
            )

        self._jobs[job_id] = Job(job_id, priority, duration, deps, len(self._jobs))
        for dep in deps:
            self._dependents[dep].append(job_id)

    # ----------------------------------------------------------------- cancel
    def cancel(self, job_id: str) -> set[str]:
        if job_id not in self._jobs:
            raise UnknownJobError(job_id)
        if job_id in self._cancelled:
            return set()

        newly_cancelled: set[str] = set()
        queue = deque([job_id])
        while queue:
            current = queue.popleft()
            if current in self._cancelled:
                continue
            self._cancelled.add(current)
            newly_cancelled.add(current)
            queue.extend(self._dependents.get(current, ()))
        return newly_cancelled

    # --------------------------------------------------------------- planning
    def execution_order(self) -> list[str]:
        return [run.job_id for run in self.simulate(workers=1).runs]

    def simulate(self, workers: int) -> Schedule:
        if workers < 1:
            raise SchedulerError("workers must be >= 1")

        active = self._active_jobs()
        self._validate(active)

        remaining_deps = {job.id: len(job.depends_on) for job in active.values()}
        ready = [self._ready_key(job) for job in active.values() if not job.depends_on]
        heapq.heapify(ready)
        free_workers = list(range(workers))
        running: list[tuple[int, int, str]] = []  # (end, worker, job_id)
        runs: list[Run] = []
        now = 0

        while ready or running:
            # Fill every free worker before advancing time.
            while ready and free_workers:
                _, _, job_id = heapq.heappop(ready)
                worker = heapq.heappop(free_workers)
                end = now + active[job_id].duration
                runs.append(Run(job_id, worker, now, end))
                heapq.heappush(running, (end, worker, job_id))

            if not running:
                break

            # Advance to the next completion and release *all* jobs ending then,
            # so simultaneous completions compete fairly for workers.
            now = running[0][0]
            while running and running[0][0] == now:
                _, worker, job_id = heapq.heappop(running)
                heapq.heappush(free_workers, worker)
                for dependent in self._dependents.get(job_id, ()):
                    if dependent not in active:
                        continue
                    remaining_deps[dependent] -= 1
                    if remaining_deps[dependent] == 0:
                        heapq.heappush(ready, self._ready_key(active[dependent]))

        return Schedule(runs=runs, makespan=now)

    # ---------------------------------------------------------------- helpers
    def _active_jobs(self) -> dict[str, Job]:
        return {jid: job for jid, job in self._jobs.items() if jid not in self._cancelled}

    @staticmethod
    def _ready_key(job: Job) -> tuple[int, int, str]:
        return (-job.priority, job.seq, job.id)

    def _validate(self, active: dict[str, Job]) -> None:
        for job in active.values():
            for dep in job.depends_on:
                if dep not in active:
                    raise UnknownDependencyError(
                        f"job {job.id!r} depends on unknown job {dep!r}"
                    )
        cycle = self._find_cycle(active)
        if cycle:
            raise CycleError(cycle)

    @staticmethod
    def _find_cycle(active: dict[str, Job]) -> list[str] | None:
        """Iterative 3-colour DFS; returns one cycle's members in order."""
        WHITE, GREY, BLACK = 0, 1, 2
        colour = dict.fromkeys(active, WHITE)

        for root in sorted(active, key=lambda j: active[j].seq):
            if colour[root] != WHITE:
                continue
            path: list[str] = []
            stack = [(root, iter(active[root].depends_on))]
            colour[root] = GREY
            path.append(root)
            while stack:
                node, children = stack[-1]
                child = next(children, None)
                if child is None:
                    colour[node] = BLACK
                    path.pop()
                    stack.pop()
                elif colour[child] == GREY:
                    return path[path.index(child):]
                elif colour[child] == WHITE:
                    colour[child] = GREY
                    path.append(child)
                    stack.append((child, iter(active[child].depends_on)))
        return None
