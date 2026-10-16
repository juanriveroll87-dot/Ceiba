# Inference Job Scheduler

An AI platform runs pipelines of jobs on a pool of GPU workers. One pipeline
might look like `fetch-data → tokenize → embed → index → evaluate`. Each job has:

| Field        | Type          | Meaning                                                    |
|--------------|---------------|------------------------------------------------------------|
| `job_id`     | `str`         | Unique identifier                                          |
| `priority`   | `int`         | Higher runs first when several jobs are ready              |
| `duration`   | `int` (≥ 1)   | Time units the job occupies a worker                       |
| `depends_on` | list of `str` | Jobs that must **finish** before this one can **start**    |

You'll build a `Scheduler` in stages. Each part builds on the previous one.
**Finish one part before you start the next one.** We care more about clean,
correct, well-reasoned code for the parts you finish than about reaching the
end.

You can use any language, but starter code and tests are provided in Python
(standard library only):

```bash
python -m unittest -v        # run from this directory
```

---

## Part 1: Valid execution order

```python
s = Scheduler()
s.submit("tokenize", priority=1, duration=2, depends_on=["fetch"])
s.submit("fetch",    priority=1, duration=1)
s.execution_order()  # -> ["fetch", "tokenize"]
```

Implement `submit(job_id, priority, duration, depends_on=())` and
`execution_order() -> list[str]`.

* `execution_order` returns an order to run **every** job on a single worker
  that respects all dependencies.
* When more than one job is ready to run, choose the one with the **highest
  priority**. Break ties by **submission order** (earlier first).
* Jobs can be submitted in any order, so a dependency may be submitted *after*
  the job that needs it.
* Errors (all subclasses of `SchedulerError`):
  * `DuplicateJobError`: `submit` is called with an id that already exists.
  * `SchedulerError`: `duration < 1`.
  * `UnknownDependencyError`: raised by `execution_order` if a job depends on an
    id that was never submitted.
  * `CycleError`: raised by `execution_order` if the dependencies form a cycle.
    Its `.cycle` attribute must list the ids of the jobs in one cycle.

## Part 2: Simulating a worker pool

Implement `simulate(workers: int) -> Schedule`.

Simulate running every job on `workers` identical workers, numbered
`0 … workers-1`:

* Time starts at `0`.
* As long as there is a free worker and a ready job, the highest-priority ready
  job starts on the **lowest-numbered free worker**. Use the same tie-break
  rules as Part 1.
* A job that starts at time `t` finishes at `t + duration`. That frees its worker
  and may make its dependents ready **at that same instant**.
* If several jobs finish at the same time, release **all** of them before you
  assign new work.
* Return a `Schedule` that has:
  * `runs`: one `Run(job_id, worker, start, end)` for each job, in the order the
    jobs started.
  * `makespan`: the time the last job finishes (`0` if there are no jobs).
* Validation errors are the same as in Part 1. `workers < 1` raises
  `SchedulerError`.

## Part 3: Cancellation

Implement `cancel(job_id) -> set[str]`.

* Cancel the job and every job that depends on it, directly or transitively.
  Cancelled jobs are left out of `execution_order` and `simulate`.
* Return the set of jobs that **this call** cancelled. Cancelling a job that's
  already cancelled returns an empty set.
* `UnknownJobError`: `job_id` was never submitted.
* `CancelledDependencyError`: `submit` is called with a dependency that's
  already cancelled.

## Part 4: Code review (discussion)

Open `review_snippet.py`. A teammate wrote it, and it "works". Spend about 10
minutes reviewing it as you would a pull request. What would you change, why,
and in what order of importance? You don't need to rewrite it.

---

### Ground rules

* Ask clarifying questions at any time. Some ambiguity in the spec is on purpose.
* Think out loud. Your reasoning matters as much as your final code.
* Use whatever docs or references you normally would. Please don't use AI code
  generation.
* The provided tests are not exhaustive.
