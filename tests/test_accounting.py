from __future__ import annotations

import unittest
from dataclasses import MISSING, dataclass, fields
from types import SimpleNamespace

from sericite.accounting import AccountRoute, Meter
from sericite.engine import SericiteEngine, _NativeFunction
from sericite.errors import SericiteError


@dataclass(eq=False)
class FakeAccount:
    vm_id: int
    parent_id: int | None
    instruction_count: int = 0
    alloc_bytes: int = 0
    max_instructions: int = 1000
    max_total_bytes: int = 1000

    @property
    def limits(self) -> SimpleNamespace:
        return SimpleNamespace(
            max_instructions=self.max_instructions,
            max_total_bytes=self.max_total_bytes,
        )


class AccountRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = FakeAccount(0, None)
        self.home = FakeAccount(1, 0)
        self.caller = FakeAccount(2, 0)
        self.accounts = {account.vm_id: account for account in self.accounts_list}

    @property
    def accounts_list(self) -> list[FakeAccount]:
        return [self.root, self.home, self.caller]

    def route(self, *accounts: FakeAccount) -> AccountRoute:
        return AccountRoute(*accounts, resolve=self.accounts.__getitem__)

    def test_shared_ancestors_are_charged_once(self) -> None:
        self.route(self.home, self.caller).charge(work=5, allocation=7)
        self.assertEqual(
            (self.home.instruction_count, self.caller.instruction_count),
            (5, 5),
        )
        self.assertEqual((self.root.instruction_count, self.root.alloc_bytes), (5, 7))

    def test_failed_charge_has_no_partial_commit(self) -> None:
        self.caller.max_instructions = 4
        with self.assertRaises(SericiteError) as ctx:
            self.route(self.home, self.caller).charge(work=5)
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(
            [account.instruction_count for account in self.accounts_list],
            [0, 0, 0],
        )


class AllocationPermitTests(unittest.TestCase):
    def test_permit_is_bound_and_one_shot(self) -> None:
        account = FakeAccount(0, None)
        owner = object()
        permit = Meter(AccountRoute(account, resolve=lambda _: None)).reserve(
            owner, "input", 8
        )
        with self.assertRaises(SericiteError):
            permit.consume(object(), "input", 8)
        with self.assertRaises(SericiteError):
            permit.consume(owner, "input", 9)
        permit.consume(owner, "input", 8)
        with self.assertRaises(SericiteError):
            permit.consume(owner, "input", 8)
        self.assertEqual(account.alloc_bytes, 8)


class NativeCostContractTests(unittest.TestCase):
    def test_native_home_work_and_allocation_are_mandatory(self) -> None:
        native_fields = {item.name: item for item in fields(_NativeFunction)}
        for name in ("home", "work", "allocation"):
            self.assertIs(native_fields[name].default, MISSING)

    def test_unknown_vm_method_cost_contract_fails_closed(self) -> None:
        engine = SericiteEngine()
        handle = engine.create_root("")
        with self.assertRaises(SericiteError) as work_error:
            engine._vm_method_work(handle, "future_method", (), {})
        with self.assertRaises(SericiteError) as allocation_error:
            engine._vm_method_allocation(
                handle,
                "future_method",
                (),
                {"_caller_context": engine._contexts[0]},
            )
        self.assertEqual(work_error.exception.kind, "internal_error")
        self.assertEqual(allocation_error.exception.kind, "internal_error")


if __name__ == "__main__":
    unittest.main()
