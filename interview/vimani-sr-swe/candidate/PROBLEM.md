# Presupuesto vs. Ejercido: Cost Code Rollups

Vimani AI connects the whole real estate development lifecycle (budget,
procurement, warehouse, schedule, billing) through **one shared cost code
catalog**. Every peso budgeted, committed or spent on a project (*obra*) is
tagged with a cost code. Because every module uses the same codes, a site
manager (*residente*) can compare what was budgeted with what was spent
(*presupuesto vs. ejercido*) right now, instead of finding an overrun at
month-end close (*cierre de mes*), 30 days after the concrete was poured.

You'll build the core of that comparison in stages. **Finish one part before
you start the next one.** We care more about correct, clear, well-reasoned code
for the parts you finish than about reaching the end.

Use any language you like. Starter code and tests are in Python (standard
library only):

```bash
python -m unittest -v        # run from this directory
```

### Glossary

| Term | Meaning |
|------|---------|
| **Cost code** | Identifies what money is spent on. Hierarchical, written with dots: `03` → `03.02` → `03.02.010`. |
| **Commitment** | Money promised but not yet paid, such as an approved purchase order from a *requisición*. |
| **Actual** (*ejercido*) | Money actually spent, such as an invoice or a warehouse receipt (*entrada de almacén*). |
| **Exposure** | `committed + actual`: how much of the budget is already used up. |

---

## Part 1: The catalog

```python
catalog = Catalog(common_depth=2)
catalog.add("03", "Estructura")
catalog.add("03.02", "Concreto")

obra = Project("Torre Norte", catalog)
obra.add_code("03.02.010", "Columnas")
obra.add_code("03.02.020", "Losas")
```

* A code is one or more non-empty alphanumeric segments joined by `.`. Its
  **level** is the number of segments. Its **parent** is the code without its
  last segment (`03.02.010` → `03.02`). Level-1 codes have no parent.
* The **template** `Catalog` is shared by every project so that history can be
  compared across projects. It holds levels `1 … common_depth` only.
* A `Project` starts from a **snapshot** of the template. Changes made to the
  template afterwards don't affect it. Each project adds its own codes, which
  must be **deeper than `common_depth`**, because projects genuinely differ.
* Errors (all subclasses of `BudgetError`):
  * `InvalidCodeError`: malformed code (`""`, `"03..1"`, `"03.0 1"`).
  * `DuplicateCodeError`: the code already exists.
  * `UnknownCodeError`: the parent doesn't exist.
  * `LevelError`: a template code deeper than `common_depth`, or a project code
    at or above it.

## Part 2: Budget, postings and rollups

```python
obra.set_budget("03.02.010", "100000.00")
obra.post("REQ-881", "03.02.010", "commitment", "60000.00")
obra.post("INV-112", "03.02.010", "actual", "45000.50")

obra.report("03")
# Line(code="03", name="Estructura", budget=Decimal("100000.00"),
#      committed=Decimal("60000.00"), actual=Decimal("45000.50"),
#      exposure=Decimal("105000.50"), remaining=Decimal("-5000.50"))
```

* `set_budget(code, amount)` **sets** (replaces) the budget of a code.
* `post(txn_id, code, kind, amount)` records a transaction. `kind` is
  `"commitment"` or `"actual"`. Amounts can be negative (credits, returns,
  releasing a commitment).
* Budgets and postings go only on **leaf** codes (codes with no sub-codes).
  Otherwise, raise `NotALeafError`.
* `report(code)` returns totals for the code **plus everything below it**.
* Amounts arrive as decimal strings (or `Decimal`). Totals must be **exact to
  the cent**. Report values are `Decimal`. A malformed amount, or a negative
  budget, raises `InvalidAmountError`.
* **Field sync.** Phones on a jobsite have unreliable connectivity, so clients
  retry, and the same transaction can arrive more than once.
  * The same `txn_id` with the same data is a no-op. `post` returns `False`
    (`True` when it applies a transaction).
  * The same `txn_id` with **different** data raises
    `DuplicateTransactionError`.
* Adding a sub-code under a code that already has a budget or postings raises
  `CodeInUseError`. The money would end up attached to a non-leaf code.
* `report` on a code that doesn't exist raises `UnknownCodeError`.
* A project can have thousands of codes and hundreds of thousands of postings,
  and dashboards call `report` constantly.

## Part 3: Early warnings

The goal is to flag overruns **before** month-end close.

```python
obra.alerts(threshold="0.05", limit=10)
# -> [Alert(code="03.02.010", budget=Decimal("100000.00"),
#           exposure=Decimal("105000.50"), overrun=Decimal("5000.50"))]
```

`alerts(threshold="0", depth=None, limit=None) -> list[Alert]`

* Flag a code when `exposure > budget × (1 + threshold)`. For example,
  `threshold="0.05"` allows 5% over budget before flagging.
* **Spending on a code with no budget must be flagged.**
* Which codes to look at:
  * `depth=None`: leaf codes.
  * `depth=n`: codes at level `n`, using their rolled-up totals.
* Sort by `overrun` (`exposure − budget`), largest first. Break ties by code,
  ascending. `limit` returns only the first `limit` alerts.
* A negative `threshold` raises `InvalidAmountError`.

## Part 4: Code review (discussion)

Open `review_snippet.py`. A teammate wrote it for the AI layer, and it
"works". Spend about 10 minutes reviewing it as you would a pull request. What
would you change, why, and in what order? You don't need to rewrite it.

---

### Ground rules

* Ask clarifying questions at any time. Some ambiguity is on purpose.
* Think out loud. Your reasoning matters as much as your code.
* Use any docs you normally would. For this live session, please don't use AI
  code generation. We'll talk about how you use those tools separately.
* The provided tests are not exhaustive.
