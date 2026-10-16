"""Reference solution — INTERVIEWER ONLY. Do not share with candidates.

Design notes
------------
* Each cost code is a `_Node` in a tree. The parent is implied by the code
  itself ("03.02.010" -> "03.02"), so the tree is a dict keyed by code plus a
  child list per node.
* Totals (budget / committed / actual) are stored *rolled up*: every write
  walks from the leaf to the root, adding the delta to each ancestor.
  Writes cost O(depth) and `report()` costs O(1). Catalogs are shallow
  (3–5 levels) and reports are read far more often than they are written,
  so this is the right trade.
* Money is `Decimal`, parsed from strings. Floats never touch a total.
* `post()` is idempotent on `txn_id`. Field devices retry on flaky
  connections, so the same transaction *will* arrive twice. A replay with the
  same payload is a no-op; the same id with a different payload is a conflict
  that has to be raised, never silently ignored or overwritten.
* Projects snapshot the template at creation time, so later template edits
  don't change a running project's structure.
"""

from __future__ import annotations

import heapq
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

ZERO = Decimal("0")
KINDS = ("commitment", "actual")
_SEGMENT = re.compile(r"[0-9A-Za-z]+")


class BudgetError(ValueError):
    """Base class for all errors raised by this module."""


class InvalidCodeError(BudgetError):
    pass


class DuplicateCodeError(BudgetError):
    pass


class UnknownCodeError(BudgetError, KeyError):
    pass


class LevelError(BudgetError):
    pass


class NotALeafError(BudgetError):
    pass


class CodeInUseError(BudgetError):
    pass


class InvalidAmountError(BudgetError):
    pass


class DuplicateTransactionError(BudgetError):
    pass


@dataclass(frozen=True)
class Line:
    code: str
    name: str
    budget: Decimal
    committed: Decimal
    actual: Decimal
    exposure: Decimal   # committed + actual
    remaining: Decimal  # budget - exposure


@dataclass(frozen=True)
class Alert:
    code: str
    budget: Decimal
    exposure: Decimal
    overrun: Decimal    # exposure - budget


@dataclass
class _Node:
    code: str
    name: str
    parent: str | None
    depth: int
    children: list[str] = field(default_factory=list)
    budget: Decimal = ZERO
    committed: Decimal = ZERO
    actual: Decimal = ZERO
    has_entries: bool = False  # budget set or anything posted (leaves only)


@dataclass(frozen=True)
class _Txn:
    code: str
    kind: str
    amount: Decimal


# ------------------------------------------------------------------ helpers
def _parse_code(code: str) -> tuple[str | None, int]:
    """Return (parent_code, depth) or raise InvalidCodeError."""
    if not isinstance(code, str):
        raise InvalidCodeError(f"code must be a string, got {code!r}")
    segments = code.split(".")
    if not all(_SEGMENT.fullmatch(s) for s in segments):
        raise InvalidCodeError(f"malformed cost code {code!r}")
    parent = ".".join(segments[:-1]) or None
    return parent, len(segments)


def _parse_amount(amount: str | Decimal) -> Decimal:
    if isinstance(amount, float):
        raise InvalidAmountError("amounts must be strings or Decimal, not float")
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidAmountError(f"invalid amount {amount!r}") from None
    if not value.is_finite():
        raise InvalidAmountError(f"invalid amount {amount!r}")
    return value


class _Tree:
    """Code tree shared by Catalog and Project."""

    def __init__(self) -> None:
        self._nodes: dict[str, _Node] = {}

    def _insert(self, code: str, name: str) -> _Node:
        parent, depth = _parse_code(code)
        if code in self._nodes:
            raise DuplicateCodeError(code)
        if parent is not None and parent not in self._nodes:
            raise UnknownCodeError(f"parent {parent!r} of {code!r} does not exist")
        node = _Node(code, name, parent, depth)
        self._nodes[code] = node
        if parent is not None:
            self._nodes[parent].children.append(code)
        return node

    def _get(self, code: str) -> _Node:
        try:
            return self._nodes[code]
        except KeyError:
            raise UnknownCodeError(code) from None


# ------------------------------------------------------------------ public
class Catalog(_Tree):
    """Template catalog shared by all projects (upper levels only)."""

    def __init__(self, common_depth: int) -> None:
        super().__init__()
        if common_depth < 1:
            raise LevelError("common_depth must be >= 1")
        self.common_depth = common_depth

    def add(self, code: str, name: str) -> None:
        _, depth = _parse_code(code)
        if depth > self.common_depth:
            raise LevelError(
                f"{code!r} is level {depth}; template codes stop at level {self.common_depth}"
            )
        self._insert(code, name)


class Project(_Tree):
    def __init__(self, name: str, catalog: Catalog) -> None:
        super().__init__()
        self.name = name
        self.common_depth = catalog.common_depth
        self._txns: dict[str, _Txn] = {}
        # Dicts keep insertion order and parents are always inserted first.
        for node in catalog._nodes.values():
            self._insert(node.code, node.name)

    # ------------------------------------------------------------ Part 1
    def add_code(self, code: str, name: str) -> None:
        parent, depth = _parse_code(code)
        if depth <= self.common_depth:
            raise LevelError(
                f"{code!r} is level {depth}; levels 1-{self.common_depth} come from the template"
            )
        if parent in self._nodes and self._nodes[parent].has_entries:
            raise CodeInUseError(f"{parent!r} already has budget or postings")
        self._insert(code, name)

    # ------------------------------------------------------------ Part 2
    def set_budget(self, code: str, amount: str | Decimal) -> None:
        node = self._leaf(code)
        value = _parse_amount(amount)
        if value < ZERO:
            raise InvalidAmountError("budget cannot be negative")
        self._propagate(node, budget=value - node.budget)
        node.has_entries = True

    def post(self, txn_id: str, code: str, kind: str, amount: str | Decimal) -> bool:
        if kind not in KINDS:
            raise BudgetError(f"kind must be one of {KINDS}, got {kind!r}")
        node = self._leaf(code)
        txn = _Txn(code, kind, _parse_amount(amount))

        existing = self._txns.get(txn_id)
        if existing is not None:
            if existing == txn:
                return False  # replay from a retrying client
            raise DuplicateTransactionError(
                f"{txn_id!r} was already posted with different data: {existing}"
            )

        self._txns[txn_id] = txn
        self._propagate(node, **{"committed" if kind == "commitment" else "actual": txn.amount})
        node.has_entries = True
        return True

    def report(self, code: str) -> Line:
        n = self._get(code)
        exposure = n.committed + n.actual
        return Line(n.code, n.name, n.budget, n.committed, n.actual, exposure, n.budget - exposure)

    # ------------------------------------------------------------ Part 3
    def alerts(
        self,
        threshold: str | Decimal = "0",
        depth: int | None = None,
        limit: int | None = None,
    ) -> list[Alert]:
        tolerance = _parse_amount(threshold)
        if tolerance < ZERO:
            raise InvalidAmountError("threshold cannot be negative")
        if limit is not None and limit < 0:
            raise BudgetError("limit cannot be negative")

        def in_scope(n: _Node) -> bool:
            return n.depth == depth if depth is not None else not n.children

        flagged = []
        for n in self._nodes.values():
            if not in_scope(n):
                continue
            exposure = n.committed + n.actual
            # Multiply instead of dividing: no special case for zero budget,
            # and unbudgeted spend (budget 0, exposure > 0) is flagged.
            if exposure > n.budget * (1 + tolerance):
                flagged.append(Alert(n.code, n.budget, exposure, exposure - n.budget))

        order = lambda a: (-a.overrun, a.code)  # noqa: E731
        if limit is None:
            return sorted(flagged, key=order)
        return heapq.nsmallest(limit, flagged, key=order)

    # ------------------------------------------------------------ helpers
    def _leaf(self, code: str) -> _Node:
        node = self._get(code)
        if node.children:
            raise NotALeafError(f"{code!r} has sub-codes; post to a leaf code")
        return node

    def _propagate(self, node: _Node, **deltas: Decimal) -> None:
        current: _Node | None = node
        while current is not None:
            for attr, delta in deltas.items():
                setattr(current, attr, getattr(current, attr) + delta)
            current = self._nodes[current.parent] if current.parent else None
