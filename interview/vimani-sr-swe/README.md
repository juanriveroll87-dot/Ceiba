# Vimani AI: Senior Software Engineer / Tech Lead Exercise

## Presupuesto vs. Ejercido: Cost Code Rollups

**Format:** 75-minute live pairing session (a take-home variant is described below)
**Signals:** (1) problem solving, (2) data structures, (3) logical, maintainable code
**Language:** any. The starter code and tests are Python 3.10+ standard library, so there's nothing to install.

```
vimani-sr-swe/
├── candidate/                 ← share ONLY this folder
│   ├── PROBLEM.md             problem statement (Parts 1–4) + glossary
│   ├── budget.py              starter skeleton
│   ├── test_budget.py         11 visible tests
│   └── review_snippet.py      Part 4: AI cost-code classifier to review
├── interviewer/               ← never share
│   ├── budget.py              reference solution
│   ├── test_hidden.py         26 hidden edge-case + scale tests
│   └── check.sh               ./check.sh path/to/candidate/budget.py
└── architecture/              ← round-2 system design reference (never share)
    ├── AI_COORDINATION.md     how the LLM coordinates field actors, with worked examples
    └── prototype/             runnable demo + 17 guardrail tests (python demo.py)
```

> The job posting says product details are shared during the interview.
> `PROBLEM.md` explains the cost code spine and the month-end-close problem, so
> share it only once the candidate is in the interview loop.

## Why this exercise

It's the first thing this hire will actually build. The company README says
*"The first commits will be the cost code model"* and calls the catalog *"the
most consequential design decision in the system."* The exercise is a small,
working version of that model, and it tests the product's non-negotiable
constraints directly:

| Vimani constraint | Where the exercise tests it |
|---|---|
| *"A wrong number costs money"* | Exact `Decimal` money, rejecting `NaN`, flagging unbudgeted spend, no double-counting |
| *"Field conditions are hostile… intermittent connectivity"* | Idempotent `post()` for retried transactions, and conflict detection |
| *"Upper levels common, lower levels free per project"* | `common_depth` split between template and project, with template snapshots |
| *"Flag budget deviations before month-end close"* | Part 3 alerts count commitments, not only invoices |
| *"Confidence thresholds, human review, deterministic fallbacks; acceptance rate is tracked"* | Part 4 code review of an LLM cost-code classifier |
| *"AI tools are… dangerous where being wrong is quiet. Most of this domain is the second kind."* | Most hidden tests catch **quiet** bugs: totals that are slightly wrong, with no exception raised |

How each part maps to the three signals:

| Part | Task | Problem solving | Data structures | Maintainability |
|------|------|-----------------|-----------------|-----------------|
| 1 (15 min) | Hierarchical catalog: template + project | Parsing, validation, the snapshot question | **Tree** (hash map + child lists), parent derived from the code | Errors that say what went wrong, clear template/project boundary |
| 2 (25 min) | Budget, postings, rollups, idempotency | Read/write trade-off, retry semantics | **Rolled-up totals updated along the ancestor path** (O(depth) write, O(1) read); id → txn map for deduplication | Money type, writes that fail leave no partial state, one place where totals change |
| 3 (10 min) | Early-warning alerts | Zero-budget edge case, threshold boundary | **Heap** for top-k | Reuses Part 2 rollups and doesn't recompute them |
| 4 (10 min) | Review an LLM classifier PR | Ranks risks by what they cost in money | Shared cache keyed wrong | Tech-lead judgment on AI in production |

## Session plan (75 min)

| Time  | Activity |
|-------|----------|
| 0–5   | Intro. Share the `candidate/` folder; the candidate reads PROBLEM.md. Spend 1 minute on the domain: "a residente needs to know about the overrun this week, not at cierre de mes." |
| 5–20  | **Part 1.** Expect questions before code is written. |
| 20–45 | **Part 2.** The core of the exercise. Watch the money type and the rollup strategy. |
| 45–55 | **Part 3.** If time is short, a verbal design is acceptable. |
| 55–67 | **Part 4.** Code review discussion. |
| 67–75 | Candidate's questions. |

A senior / tech-lead candidate should finish Parts 1–2 cleanly, at least design
Part 3, and lead the Part 4 discussion. After the interview, run
`interviewer/check.sh <their budget.py>`. The hidden-test results are one input
among several, not the score.

## Ambiguities planted on purpose

Good candidates ask about these. Answers to give if asked:

| Question | Answer |
|----------|--------|
| Rounding? How many decimal places? | Don't round. Keep amounts exact as given. |
| Currency? | One currency per project. (Multi-currency for the MX/US customers is a good extension question.) |
| Does an invoice consume its purchase-order commitment automatically? | Not here. The client posts a negative commitment to release it. Ask what they'd do in a real system. |
| Can a template leaf with no project sub-codes take a budget? | Yes. It's a leaf. |
| What does `report` return for a code with no activity? | All zeros. |
| If `post` fails validation, is the `txn_id` used up? | No. A failed write leaves no trace. |
| Does `"100"` vs `"100.00"` count as different data? | No. Same money, so it's a replay. |
| Concurrency? Persistence? | Single-threaded and in memory for this exercise. Discuss these later. |
| Can a code be renamed, moved or deleted? | Out of scope. A great extension question. |

## Reference approach

See `interviewer/budget.py` (~275 lines).

**Part 1: tree keyed by code.**
- Use `dict[code → Node]`. Each node has `parent`, `children` and `depth`. The
  parent is the code with its last segment removed, so no separate parent
  field is needed in the input.
- Validate segments with a regex, not by splitting and hoping.
- **Prefix trap:** code that walks the tree with `startswith` counts `03.10`
  as a child of `03.1`. Compare segments, or follow parent links.
- **Snapshot:** a project copies the template at creation. Sharing node
  objects with the template would let one project's codes leak into others.

**Part 2: keep totals rolled up as you write.**
- Each node stores subtree totals for `budget`, `committed` and `actual`. On
  every write, walk from the leaf to the root and add the delta. That's
  O(depth), and catalogs are 3–5 levels deep. `report` is then O(1).
- Alternatives, in increasing order of quality:
  - **Scan every posting on each report:** O(P) per read. Fails the scale test.
  - **Sum the subtree on each report:** O(subtree) per read. Passes, but should
    be justified.
  - **Rolled up on write:** best for a read-heavy dashboard. A strong
    candidate *says* this trade-off out loud.
- `set_budget` replaces, so it propagates `new − old`, not `new`.
- **Idempotency:** keep `txn_id → (code, kind, amount)`. Compare the full
  payload: a match is a no-op returning `False`; a difference raises. Validate
  **everything before changing anything**, so a rejected post burns nothing.
- **Money:** parse with `Decimal(str)`. Reject floats and non-finite values.
  `Decimal("NaN")` parses without error and turns every total above it into
  NaN.

**Part 3: filter, then pick the top k.**
- Flag when `exposure > budget * (1 + threshold)`. **Multiply, don't divide.**
  A ratio `exposure / budget` divides by zero on unbudgeted codes, and those
  are exactly the ones the business most needs to see.
- `heapq.nsmallest(limit, alerts, key=(-overrun, code))` is O(n log k). A full
  sort is fine to mention.
- `depth=n` uses the rolled-up totals, so a parent nets savings against
  overruns. Candidates who take the max of the children get this wrong.

## Hints ladder

Give hints one at a time, only after about 3 minutes of being stuck. Record
each hint you give.

1. "What shape does the catalog have, and how do you find a code's parent?"
2. "A dashboard calls `report` thousands of times per minute. Where should the
   work happen?" → on write
3. "What happens when a phone with bad signal sends the same invoice twice?"
4. "What type are you storing money in? What's `0.1 + 0.2` in it?"
5. (Part 3) "What should happen for a code with no budget that has spending?"

## Part 4 answer key: `review_snippet.py`

Roughly in order of severity. A strong candidate starts with *wrong numbers
that nobody notices*, not with style.

| Sev | Issue |
|-----|-------|
| 🔴 | **Cache returns another requisition's line.** `_cache` stores the whole `line` dict, so a later line with the same description gets back the *earlier* line's `id`, `quantity` and `amount`. That duplicates or misstates money with no error. |
| 🔴 | **The model's code is never validated against the catalog.** A hallucinated or out-of-project code gets posted. |
| 🔴 | **No human review and a fake confidence.** A confidence above 0.3 is auto-applied. A missing confidence defaults to `1.0`, and *errors* also get `confidence = 1.0`. Real failures look like certain answers. |
| 🔴 | **The `99.99` "misc" bucket hides overruns.** Anything uncertain goes into a catch-all code, which defeats budget vs. actual: the spend never appears against the code it belongs to. It should go to a review queue with an explicit "unclassified" state. |
| 🔴 | **`float(line["amount"])`**: money as float. |
| 🟠 | **Module-level `_cache` shared across projects and customers.** Lower catalog levels differ per project, so a code learned on project A is applied to project B. It also grows without bound and isn't thread-safe. |
| 🟠 | **Bare `except:`** hides parse errors, timeouts and bugs alike, with no logging. |
| 🟠 | **Prompt injection.** Free text typed in the field goes straight into the prompt. |
| 🟠 | **Mutates the caller's input** (`line[...] = ...`) and returns those same objects. |
| 🟡 | **Acceptance rate can't be measured.** Nothing records the suggested code, its confidence, the model/prompt version, or what the residente finally chose. Without that there's no acceptance metric and no test set to evaluate changes against. The company README requires both. |
| 🟡 | One LLM call per line with no batching or timeout, and the whole catalog is stringified into every prompt. Should retrieve candidate codes first, for example from codes with similar past descriptions. |
| 🟡 | Doesn't work offline. In the field there should be a deterministic fallback, such as the last code used for this item on this project. |
| ⚪ | Magic numbers (`0.3`, `"99.99"`), no type hints, no tests. |

**Tech-lead follow-up** (2–3 min): *"A junior engineer wrote this with an AI
assistant. How do you give feedback, and what team standard would you add so
this doesn't happen again?"* Look for specific, kind, teachable answers, such
as eval-gated changes, a rule that the model never writes money directly, and
a review checklist.

## Scoring rubric

Score each dimension from 1 to 4. **Hire bar: an average of 3 or more, with no
dimension at 1.** This is the first technical hire, so weigh dimension 3 and
the Part 4 discussion heavily.

### 1. Problem solving

| Score | Evidence |
|-------|----------|
| 4 | Asks sharp domain questions (commitment release, rounding, replay semantics) before coding. States the read/write trade-off with complexity. Tests the quiet edge cases on their own: zero budget, NaN, a rejected post, a replay. Debugs from evidence. |
| 3 | Gets to the tree + rollup design quickly. Handles idempotency and zero budget with at most one hint. Reasons about correctness out loud. |
| 2 | Needs several hints. Misses major cases, such as double counting on replay, division by zero, or floats. |
| 1 | Can't form a workable approach to Part 1 or 2 without step-by-step guidance. |

### 2. Data structures

| Score | Evidence |
|-------|----------|
| 4 | Picks a tree keyed by code with rolled-up totals unprompted and explains why in Big-O terms. Uses the txn map for deduplication and a heap for top-k. Passes the scale test. Discusses alternatives (materialized path, closure table) for when this goes into SQL. |
| 3 | Uses appropriate structures. Recomputes the subtree on read but justifies it and knows how to improve it. Correct complexity analysis. |
| 2 | Scans every posting on each report, or uses string-prefix matching for hierarchy. Fuzzy complexity. |
| 1 | Structures make the problem incorrect or intractable. |

### 3. Logical and maintainable code

| Score | Evidence |
|-------|----------|
| 4 | One place where totals change. Validates before mutating. Uses `Decimal`. Specific errors. Writes their own tests for edge cases. The Part 4 review is prioritized, focused on money and data integrity, and suggests measurement. |
| 3 | Readable and consistent. Some duplication. Uses Decimal, possibly after a hint. Part 4 finds most 🔴/🟠 issues. |
| 2 | Long methods, floats, partially applied writes, magic values. Part 4 mostly covers style. |
| 1 | Hard to follow, with hidden side effects. Misses the cache and float problems in Part 4. |

### Green flags
- Asks what a residente actually needs to see, or how the data arrives from the field.
- Writes a test before or right after each part, especially for money edge cases.
- Says what they're deliberately not doing, and why.
- Calls out where an AI assistant would likely introduce a quiet bug in this code.

### Red flags
- Uses `float` for money and defends it.
- Treats a replayed transaction as an error, or silently overwrites it.
- Builds the hierarchy with string prefixes.
- Treats the provided tests as the spec ("it passes, so it's done").
- Dismisses Part 4 issues as "the model is usually right."

## Extension questions (extra time or the follow-up interview)

1. **Change orders (*cambio de alcance*):** keep the original budget and the
   current budget separately, with an audit trail. How do the data model and
   reports change?
2. **Reclassification:** a posting was made to the wrong code. Do you edit it
   or reverse it? (Reverse it: append-only ledger.) What does that do to
   idempotency?
3. **Forecasting:** a code is 40% physically complete and 70% of its budget is
   used. How do you project the final cost and alert earlier? (Earned value:
   estimate at completion.)
4. **Persistence:** model this in Postgres. Adjacency list vs. materialized
   path vs. closure table? Where do the rolled-up totals live, and how do they
   stay correct under concurrent writes?
5. **Offline-first field app:** two phones edit offline and sync later. What
   conflicts can happen, and how do idempotency keys and an append-only log
   help?
6. **Cross-project learning:** the AI layer needs comparable history. What
   breaks if a customer is allowed to edit template levels, and how would you
   prevent it?
7. **Subcontratos:** should a subcontract be its own cost code or an attribute
   of a code? Argue both sides.

## Take-home variant

Give the `candidate/` folder with a 3-hour time box, Parts 1–3 required and
Part 4 written up in `REVIEW.md`. **AI tools are allowed**, matching how the
team works, but ask for a short `NOTES.md`: trade-offs, which tests they added,
and *where they did and didn't trust an AI tool, and why.* Then hold a
45-minute follow-up: a walkthrough, one live change (extension 1 or 2), and the
hidden-test results. Well-structured code absorbs the live change easily.

## Round 2: system design (finalists, 45–60 min)

Use the defective-delivery prompt at the end of
[`architecture/AI_COORDINATION.md`](architecture/AI_COORDINATION.md). That
document is the reference answer. It tests the part of the job the coding
exercise can't: deciding where the LLM goes in a system where *a wrong
number costs money*, and coordinating several roles (warehouse, residente,
compras, supplier, treasury, DRO) from one field signal.

## Calibration tips

- Do a dry run with 1–2 engineers or trusted peers before the first candidate,
  and adjust the timing if needed.
- All interviewers should use the same hint ladder and ambiguity answers.
- Score independently before the debrief.
