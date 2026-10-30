from __future__ import annotations

import unittest
from dataclasses import MISSING, dataclass, fields
from types import SimpleNamespace

from sericite.accounting import AccountRoute, Meter
from sericite.engine import SericiteEngine, _estimate_size, _NativeFunction
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

    def test_charge_records_actual_exhausted_account(self) -> None:
        self.home.max_instructions = 4
        with self.assertRaises(SericiteError) as ctx:
            self.route(self.home, self.caller).charge(work=5)
        self.assertEqual(ctx.exception._resource_vm_id, self.home.vm_id)

        self.caller.max_total_bytes = 4
        with self.assertRaises(SericiteError) as ctx:
            self.route(self.home, self.caller).charge(allocation=5)
        self.assertEqual(ctx.exception._resource_vm_id, self.caller.vm_id)

    def test_single_account_meter_records_exhausted_account(self) -> None:
        self.root.max_instructions = 4
        with self.assertRaises(SericiteError) as ctx:
            Meter(self.route(self.root)).work(5)
        self.assertEqual(ctx.exception._resource_vm_id, self.root.vm_id)

    def test_unlimited_account_still_accumulates_ledgers(self) -> None:
        self.root.max_instructions = -1
        self.root.max_total_bytes = -1
        route = self.route(self.root)
        route.charge(work=5, allocation=7)
        Meter(route).work(3)
        self.assertEqual(self.root.instruction_count, 8)
        self.assertEqual(self.root.alloc_bytes, 7)

    def test_finite_account_blocks_unlimited_route_atomically(self) -> None:
        self.root.max_instructions = -1
        self.root.max_total_bytes = -1
        self.home.max_instructions = -1
        self.home.max_total_bytes = -1
        self.caller.max_instructions = 4
        with self.assertRaises(SericiteError) as ctx:
            self.route(self.home, self.caller).charge(work=5, allocation=7)
        self.assertEqual(ctx.exception.kind, "resource_exhausted")
        self.assertEqual(
            [account.instruction_count for account in self.accounts_list],
            [0, 0, 0],
        )
        self.assertEqual(
            [account.alloc_bytes for account in self.accounts_list],
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


class EstimateSizeTests(unittest.TestCase):
    @staticmethod
    def meter_for(account: FakeAccount) -> Meter:
        return Meter(AccountRoute(account, resolve=lambda _: None))

    def test_flat_result_beyond_former_node_cap_is_fully_charged(self):
        account = FakeAccount(0, None, max_instructions=10**9, max_total_bytes=10**9)
        _estimate_size(["x" * 6 for _ in range(20_000)], meter=self.meter_for(account))
        self.assertEqual(account.instruction_count, 20_001)
        self.assertEqual(account.alloc_bytes, 20_000 * 8 + 20_000 * 6 * 4)

    def test_nested_result_beyond_former_node_cap_is_fully_charged(self):
        account = FakeAccount(0, None, max_instructions=10**9, max_total_bytes=10**9)
        value = {f"k{i:03d}": [0] * 100 for i in range(100)}
        _estimate_size(value, meter=self.meter_for(account))
        self.assertEqual(account.instruction_count, 10_201)
        self.assertEqual(
            account.alloc_bytes,
            100 * 16 + 100 * 4 * 4 + 100 * (100 * 8) + 10_000 * 8,
        )

    def test_estimation_failure_means_result_is_not_delivered(self):
        account = FakeAccount(0, None, max_instructions=10**9, max_total_bytes=1000)
        with self.assertRaises(SericiteError) as ctx:
            _estimate_size(
                ["x" * 6 for _ in range(20_000)], meter=self.meter_for(account)
            )
        self.assertEqual(ctx.exception.kind, "resource_exhausted")


if __name__ == "__main__":
    unittest.main()
