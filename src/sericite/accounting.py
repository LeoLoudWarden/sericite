from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .errors import SericiteError

UNLIMITED = -1


class Limits(Protocol):
    max_instructions: int
    max_total_bytes: int


class Account(Protocol):
    parent_id: int | None
    instruction_count: int
    alloc_bytes: int
    limits: Limits


class AccountRoute:
    """The deduplicated accounts whose quotas jointly constrain one causal operation."""

    def __init__(
        self,
        *accounts: Account,
        resolve: Callable[[int], Account],
    ) -> None:
        if not accounts:
            raise ValueError("an account route requires at least one account")
        ordered: list[Account] = []
        seen: set[int] = set()
        for account in accounts:
            current: Account | None = account
            while current is not None:
                if id(current) not in seen:
                    seen.add(id(current))
                    ordered.append(current)
                current = (
                    resolve(current.parent_id)
                    if current.parent_id is not None
                    else None
                )
        self._accounts = tuple(ordered)

    @property
    def accounts(self) -> tuple[Account, ...]:
        return self._accounts

    def charge(self, *, work: int = 0, allocation: int = 0) -> None:
        """Check every account before committing either charge to any account."""
        if work < 0 or allocation < 0:
            raise ValueError("charges must be non-negative")
        for account in self._accounts:
            if (
                account.limits.max_instructions != UNLIMITED
                and account.instruction_count + work > account.limits.max_instructions
            ):
                raise SericiteError(
                    "instruction limit exceeded", kind="resource_exhausted"
                )
            if (
                account.limits.max_total_bytes != UNLIMITED
                and account.alloc_bytes + allocation > account.limits.max_total_bytes
            ):
                raise SericiteError(
                    "total memory limit exceeded", kind="resource_exhausted"
                )
        for account in self._accounts:
            account.instruction_count += work
            account.alloc_bytes += allocation


class Meter:
    """The only interface trusted operations use to charge an account route."""

    def __init__(self, route: AccountRoute) -> None:
        self.route = route
        self.single_account = route.accounts[0] if len(route.accounts) == 1 else None

    def work(self, amount: int) -> None:
        if amount <= 0:
            return
        if self.single_account is None:
            self.route.charge(work=amount)
            return
        account = self.single_account
        if (
            account.limits.max_instructions != UNLIMITED
            and account.instruction_count + amount > account.limits.max_instructions
        ):
            raise SericiteError("instruction limit exceeded", kind="resource_exhausted")
        account.instruction_count += amount

    def allocate(self, amount: int) -> None:
        self.route.charge(allocation=amount)

    def reserve(self, owner: object, kind: str, amount: int) -> AllocationPermit:
        self.allocate(amount)
        return AllocationPermit(owner, kind, amount)


@dataclass(eq=False)
class AllocationPermit:
    """A one-shot authorization for a specific, already-charged resource mutation."""

    owner: object
    kind: str
    amount: int
    consumed: bool = False

    def consume(self, owner: object, kind: str, amount: int) -> None:
        if self.consumed:
            raise SericiteError(
                "allocation permit already consumed", kind="internal_error"
            )
        if self.owner is not owner or self.kind != kind or self.amount != amount:
            raise SericiteError(
                "allocation permit does not match resource mutation",
                kind="internal_error",
            )
        self.consumed = True
