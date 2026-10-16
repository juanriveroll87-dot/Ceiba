"""Presupuesto vs. Ejercido — starter code.

Implement `Catalog` and `Project` below. See PROBLEM.md for the full spec.

You may change anything in this file *except* the public names and signatures
used by the tests (the error classes, `Line`, `Alert`, `Catalog`, `Project`
and their public methods). Add helpers, classes or modules as you see fit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class BudgetError(ValueError):
    """Base class for all errors raised by this module."""


class InvalidCodeError(BudgetError):
    """Malformed cost code."""


class DuplicateCodeError(BudgetError):
    """The cost code already exists."""


class UnknownCodeError(BudgetError, KeyError):
    """A cost code (or its parent) does not exist."""


class LevelError(BudgetError):
    """A code was added at a level that belongs to the template or the project."""


class NotALeafError(BudgetError):
    """Budget or postings were sent to a code that has sub-codes."""


class CodeInUseError(BudgetError):
    """A sub-code was added under a code that already has budget or postings."""


class InvalidAmountError(BudgetError):
    """An amount that is malformed or not allowed."""


class DuplicateTransactionError(BudgetError):
    """A transaction id was reused with different data."""


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


class Catalog:
    """Template catalog shared by every project (levels 1..common_depth)."""

    def __init__(self, common_depth: int) -> None:
        self.common_depth = common_depth

    def add(self, code: str, name: str) -> None:
        """Part 1."""
        raise NotImplementedError


class Project:
    def __init__(self, name: str, catalog: Catalog) -> None:
        """Part 1. Start the project from a snapshot of the template catalog."""
        self.name = name

    def add_code(self, code: str, name: str) -> None:
        """Part 1. Add a project-specific code below the template levels."""
        raise NotImplementedError

    def set_budget(self, code: str, amount: str | Decimal) -> None:
        """Part 2."""
        raise NotImplementedError

    def post(self, txn_id: str, code: str, kind: str, amount: str | Decimal) -> bool:
        """Part 2. Return True if applied, False if it was a replay."""
        raise NotImplementedError

    def report(self, code: str) -> Line:
        """Part 2. Rolled-up totals for `code` and everything below it."""
        raise NotImplementedError

    def alerts(
        self,
        threshold: str | Decimal = "0",
        depth: int | None = None,
        limit: int | None = None,
    ) -> list[Alert]:
        """Part 3."""
        raise NotImplementedError
