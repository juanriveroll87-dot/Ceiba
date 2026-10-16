# Sr. Software Engineer Interview Exercise: Inference Job Scheduler

**Format:** 75-minute live pairing session (a take-home variant is described below)
**Signals:** (1) problem solving, (2) data structures, (3) logical, maintainable code
**Language:** any. The starter code and tests are Python 3.10+ standard library, so there's nothing to install.

```
vimani-sr-swe/
├── candidate/                 ← share ONLY this folder
│   ├── PROBLEM.md             problem statement (Parts 1–4)
│   ├── scheduler.py           starter skeleton
│   ├── test_scheduler.py      10 visible tests
│   └── review_snippet.py      Part 4 code-review snippet
└── interviewer/               ← never share
    ├── scheduler.py           reference solution
    ├── test_hidden.py         21 hidden edge-case + scale tests
    └── check.sh               ./check.sh path/to/candidate/scheduler.py
```

## Why this exercise

The problem is set in a realistic AI-platform scenario: scheduling dependent
inference and data jobs on a pool of GPU workers. Each part maps to one of the
three target signals:

| Part | Task                          | Problem solving                                        | Data structures                                     | Maintainability                                         |
|------|-------------------------------|--------------------------------------------------------|-----------------------------------------------------|---------------------------------------------------------|
| 1    | Priority-aware topo sort      | Recognizes this is a DAG problem; handles cycles and missing deps | Adjacency list, in-degree map, **heap** for ready set | Clean errors, deterministic tie-breaks                  |
| 2    | Event-driven simulation       | Models time as events, not ticks; handles simultaneous completions | **Multiple heaps** (ready / running / free workers)  | Reuses Part 1 logic instead of duplicating it           |
| 3    | Cascading cancellation        | Transitive closure; idempotency                        | **Reverse adjacency** list, BFS/DFS                 | Fits into the existing design without hacks             |
| 4    | Code review                   | Prioritizes risks                                      | Spots an unbounded cache and key collisions          | Core maintainability judgment                            |

## Session plan (75 min)

| Time     | Activity |
|----------|----------|
| 0–5      | Intro. Share the `candidate/` folder and let them read PROBLEM.md. |
| 5–25     | **Part 1.** Expect clarifying questions before any code is written. |
| 25–50    | **Part 2.** The core of the exercise. Strong candidates restructure Part 1 so the two share code. |
| 50–60    | **Part 3.** If time is short, a verbal design is acceptable. |
| 60–70    | **Part 4.** Code review discussion. |
| 70–75    | Candidate's questions. |

Most candidates won't finish everything, and that's expected. A senior
candidate should finish Parts 1–2 cleanly and at least design Part 3 well.
After the interview, run `interviewer/check.sh <their file>` and record the
hidden-test results as one input among several, not as the score.

## Ambiguities planted on purpose

Good candidates ask about these. Answers to give if asked:

| Question | Answer |
|----------|--------|
| Can a dependency be submitted after its dependent? | Yes. Validate at planning time, not at submit time. |
| Does priority override dependencies? | No. Priority only orders jobs that are already *ready*. (Follow-up: priority inversion.) |
| Should `execution_order()` mutate state or "consume" the jobs? | No. It should be repeatable. |
| Duplicate ids in `depends_on`? | Treat them as one dependency. |
| Which cycle do you report if there are several? | Any one. It must contain only cycle members, not upstream jobs. |
| Is the same job id after cancel allowed? | No. The id stays taken (`DuplicateJobError`). |

## Reference approach

**Part 1: Kahn's algorithm with a priority queue.**
- `jobs: dict[id → Job]`, `dependents: dict[id → list[id]]` (reverse edges), and
  an in-degree count per job.
- Push jobs with in-degree 0 onto a heap keyed by `(-priority, submit_seq)`.
  Pop a job, emit it, decrement its dependents' in-degree, and push any that
  reach 0.
- If jobs are left over, there's a cycle. To report *only* the cycle members,
  run a 3-colour DFS. It must be **iterative**, because the hidden tests build
  a 50k-long chain that overflows Python's recursion limit.
- Complexity: O((V + E) log V).

**Part 2: discrete-event simulation.**
- Use three heaps: `ready (-priority, seq)`, `running (end_time, worker)` and
  `free_workers (worker_id)`.
- Loop: fill every free worker from `ready`. Then jump `now` to the earliest
  end time, release **all** jobs that end at that time, and push newly ready
  dependents.
- Key insight: `execution_order() == [r.job_id for r in simulate(1).runs]`. A
  strong candidate notices this and merges the two code paths. A weaker one
  copy-pastes Part 1.

**Part 3: BFS over reverse edges.**
- Keep a `cancelled` set. BFS from the target over `dependents` and skip nodes
  already cancelled. This is why the reverse adjacency should be built at
  submit time: candidates who only stored `depends_on` have to scan every job
  on each pass, which is O(V·depth).
- Filter cancelled jobs out at planning time instead of deleting them, so the
  ids stay reserved and history is kept.

See `interviewer/scheduler.py` for the full implementation (~215 lines).

## Hints ladder

Give these one at a time, only after the candidate has been stuck for about 3
minutes. Note each hint you give in your scorecard.

1. "What kind of structure do jobs and dependencies form?" → a graph/DAG.
2. "How would you pick the *next* job efficiently among many ready ones?" → a heap.
3. (Part 2) "Does time need to advance one unit at a time?" → event-driven simulation.
4. (Part 2) "What happens if two jobs finish at exactly the same time?"
5. (Part 3) "Given a job, how do you find who depends on it without scanning everything?" → reverse edges.

## Part 4 answer key: `review_snippet.py`

Roughly in order of severity. A strong senior finds most of the 🔴 issues and
prioritizes them, rather than starting with style nits.

| Sev | Issue |
|-----|-------|
| 🔴 | **API key is printed to stdout/logs.** This is a security incident. |
| 🔴 | **Cache poisoning:** a non-200 response writes `cache[key] = None`, so every future call for that prompt returns `None` without calling the API again. |
| 🔴 | **Mutable default `cache={}`** is shared process-wide across every caller and tenant. It's unbounded (a memory leak), not thread-safe, and could serve one tenant's response to another, since the key ignores the caller. |
| 🔴 | **Key collision:** `model + prompt`, so `("gpt-4", "1x")` and `("gpt-41", "x")` collide. Use a tuple or a hash of a structured key. |
| 🟠 | **`if i == retries` is never true** (`range` stops at `retries-1`), so on failure the function returns `None` implicitly. Callers can get a string, `None`, or `"error"`, which is an inconsistent contract. It should raise a typed exception. |
| 🟠 | **Bare `except:`** catches `KeyboardInterrupt` and `SystemExit` and retries programming bugs (for example, a `KeyError` while parsing). It should catch only transient/network errors. |
| 🟠 | **Retry policy:** HTTP errors (including 429) are retried *immediately* with no backoff, and 4xx errors that can't succeed are retried too. The exception path sleeps even after the last attempt. There's no cap or jitter, and no request timeout. |
| 🟡 | Global `stats` dict: hidden shared state that isn't thread-safe. Use a metrics client. |
| 🟡 | Caching LLM output is only valid for deterministic sampling (temperature 0). That's a product decision and should be explicit. |
| 🟡 | One function does caching, retries, transport, parsing and metrics. Split those responsibilities and inject the cache and retry policy. |
| ⚪ | No type hints or docstring, `print` instead of `logging`, `retries` means "attempts", and there are no tests. |

## Scoring rubric

Score each dimension from 1 to 4. **Hire bar for Senior: an average of 3 or
more, with no dimension at 1.**

### 1. Problem solving

| Score | Evidence |
|-------|----------|
| 4 | Asks sharp clarifying questions up front. States an approach and its complexity before coding. Spots the Part 1 ≡ `simulate(1)` equivalence. Tests edge cases on their own (cycle, self-loop, simultaneous completion). Debugs methodically. |
| 3 | Gets to Kahn's/topological sort quickly. Handles cycles and missing deps. Needs at most one hint on Part 2 timing. Reasons about correctness out loud. |
| 2 | Gets there only with several hints. Misses major edge cases (cycles, out-of-order submit). Uses trial-and-error debugging. |
| 1 | Can't form a workable approach to Part 1 without step-by-step guidance. |

### 2. Data structures

| Score | Evidence |
|-------|----------|
| 4 | Picks heap, dict and reverse adjacency without prompting, and explains *why* in Big-O terms. Has an iterative DFS or a deliberate recursion plan. Passes the scale tests. Discusses the trade-offs of delete-vs-filter for cancellation. |
| 3 | Uses appropriate structures (heap for ready jobs, map-based graph). Analyzes complexity correctly when asked. Minor inefficiencies. |
| 2 | Uses lists with repeated sorting or `min()` scans (O(V²)), or scans all jobs to find dependents. Complexity analysis is fuzzy. |
| 1 | Picks structures that make the problem incorrect or intractable. Can't analyze complexity. |

### 3. Logical and maintainable code

| Score | Evidence |
|-------|----------|
| 4 | Small, well-named functions. One shared code path for ordering rules. Validation is separated from algorithm. Specific exception types. Writes their own tests. Part 3 slots in without restructuring. The Part 4 review is prioritized, with security and correctness first. |
| 3 | Readable, consistent naming. Some duplication between Parts 1 and 2. Reasonable error handling. Part 4 finds most 🔴/🟠 issues. |
| 2 | Long monolithic methods, magic values, copy-paste between parts, state mutated during planning. Part 4 focuses mainly on style. |
| 1 | Hard to follow. Hidden side effects. No meaningful error handling. Misses the security issue in Part 4. |

### Green flags
- Writes a test before or right after each part.
- Says what they're deliberately *not* doing ("I'll skip X for now because…").
- Keeps the design open to change without over-engineering.

### Red flags
- Starts coding before understanding the dependency semantics.
- Mutates job state inside `execution_order()`, so a second call returns a different result.
- Treats provided tests as the spec ("it passes, so it's done").
- Gets defensive or dismissive when given a hint.

## Extension questions (strong candidates / extra time)

Use these to probe senior and staff-level depth, as discussion only:

1. **Priority inversion:** a priority-100 job depends on a priority-0 job that
   keeps getting starved. How would you fix it? (Priority inheritance, or the
   effective priority of a job is the max over its dependents.)
2. **Critical path:** with infinite workers, what's the minimum makespan? (The
   longest path in the DAG, found by DP over topological order.) Should
   priority come from the critical path?
3. **Online scheduling:** jobs keep arriving while the simulation runs. What
   changes? (Incremental in-degree updates; cycle checks on insert.)
4. **Heterogeneous workers:** jobs need `gpu_memory`, and workers have different
   capacities. Which data structure helps? (Bucketed heaps or a sorted
   container by capacity; best-fit vs first-fit.)
5. **Failures and retries:** a job fails mid-run. How do you represent retries,
   and do downstream jobs wait or get cancelled?
6. **Scale and distribution:** 10M jobs across many scheduler nodes. What do you
   persist, and how do you avoid double-scheduling? (Leases, idempotency keys,
   partitioning by pipeline.)

## Take-home variant

Give the `candidate/` folder with a 2–3 hour time box, Parts 1–3 required and
Part 4 as written comments in a `REVIEW.md`. Ask them to add their own tests
and a short `NOTES.md` on trade-offs. Then hold a 45-minute follow-up: a
walkthrough, one change request live (for example, extension question 1), and
the hidden-test results. The live change is the best signal for
maintainability: well-structured code absorbs it easily.

## Calibration tips

- Do a dry run with 1–2 current engineers before the first candidate, and
  adjust the timing if needed.
- All interviewers should use the same hint ladder and record which hints they
  gave.
- Score independently before the debrief.
