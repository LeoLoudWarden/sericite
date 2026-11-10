import gc
import unittest

from sericite import (
    SericiteEngine,
    SericiteError,
    SericiteEvent,
    SericiteLimits,
)


class ObservationLifecycleTests(unittest.TestCase):
    def test_sink_validation_close_and_context_manager(self):
        engine = SericiteEngine()
        with self.assertRaises(SericiteError) as caught:
            engine.observe(None)
        self.assertEqual(caught.exception.kind, "type_error")

        events = []
        observation = engine.observe(events.append)
        self.assertFalse(observation.closed)
        root = engine.create_root("")
        observation.close()
        observation.close()
        root.exec("print('hidden')")
        self.assertTrue(observation.closed)
        self.assertEqual([event.kind for event in events], ["vm.created"])

        with engine.observe(events.append) as second:
            root.exec("print('visible')")
        self.assertTrue(second.closed)
        self.assertEqual(
            [event.kind for event in events],
            ["vm.created", "vm.state_changed", "vm.output", "vm.state_changed"],
        )

    def test_created_event_contains_committed_metadata(self):
        engine = SericiteEngine()
        events = []
        with engine.observe(events.append):
            root = engine.create_root(
                "",
                functions={"zeta": lambda: None, "alpha": lambda: None},
                limits=SericiteLimits(max_instructions=1234),
            )
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertIsInstance(event, SericiteEvent)
        self.assertEqual(event.sequence, 0)
        self.assertEqual(event.kind, "vm.created")
        self.assertEqual(event.vm_id, 0)
        self.assertIsNone(event.parent_id)
        self.assertEqual(event.depth, 0)
        self.assertEqual(event.data["state"], "done")
        self.assertEqual(event.data["filename"], "<sericite:vm_0>")
        self.assertEqual(event.data["limits"].max_instructions, 1234)
        self.assertEqual(event.data["functions"], ("alpha", "zeta"))
        self.assertEqual(root.snapshot()["child_count"], 0)

        with (
            engine.observe(events.append),
            self.assertRaises(SericiteError) as caught,
        ):
            engine.create_root("def broken(:")
        self.assertEqual(caught.exception.kind, "syntax_error")
        self.assertEqual(len(events), 1)

    def test_nested_vms_are_observed_without_script_cooperation(self):
        engine = SericiteEngine()
        events = []
        with engine.observe(events.append):
            root = engine.create_root(
                'child = VM("grandchild = VM(\'print(\\"deep\\")\')\\n'
                'grandchild.run()")\nchild.run()'
            )
            self.assertEqual(root.run(), "")

        created = [event for event in events if event.kind == "vm.created"]
        self.assertEqual([event.vm_id for event in created], [0, 1, 2])
        self.assertEqual([event.parent_id for event in created], [None, 0, 1])
        self.assertEqual([event.depth for event in created], [0, 1, 2])
        output = [event for event in events if event.kind == "vm.output"]
        self.assertEqual(
            [(event.vm_id, event.data["text"]) for event in output], [(2, "deep\n")]
        )
        done = [
            event
            for event in events
            if event.kind == "vm.state_changed" and event.data["new_state"] == "done"
        ]
        self.assertEqual([event.vm_id for event in done], [2, 1, 0])
        self.assertEqual(
            [event.sequence for event in events],
            sorted(event.sequence for event in events),
        )

    def test_explicit_dispose_cascades_and_is_idempotent(self):
        engine = SericiteEngine()
        events = []
        with engine.observe(events.append):
            root = engine.create_root(
                "child = VM(\"grandchild = VM('x = 1')\")\nchild.run()"
            )
            root.run()
            root.dispose()
            root.dispose()

        terminated = [
            event
            for event in events
            if event.kind == "vm.state_changed"
            and event.data["new_state"] == "terminated"
        ]
        self.assertEqual([event.vm_id for event in terminated], [2])
        self.assertTrue(all(event.data["reason"] == "dispose" for event in terminated))
        disposed = [event for event in events if event.kind == "vm.disposed"]
        self.assertEqual([event.vm_id for event in disposed], [2, 1, 0])
        self.assertTrue(
            all(
                event.data == {"reason": "dispose", "state": "terminated"}
                for event in disposed
            )
        )


class ObservationOutputTests(unittest.TestCase):
    def test_unbuffered_output_precedes_failing_host_writer(self):
        events = []

        def fail_writer(text):
            raise RuntimeError("writer failed")

        engine = SericiteEngine()
        with engine.observe(events.append):
            root = engine.create_root(
                'print("committed")',
                output_writer=fail_writer,
                buffer_output=False,
            )
            with self.assertRaises(SericiteError) as caught:
                root.run()
        self.assertEqual(caught.exception.kind, "internal_error")
        self.assertEqual(root.stdout(), "")
        output = [event for event in events if event.kind == "vm.output"]
        self.assertEqual([event.data["text"] for event in output], ["committed\n"])
        failed = events[-1]
        self.assertEqual(failed.kind, "vm.state_changed")
        self.assertEqual(failed.data["new_state"], "error")
        self.assertEqual(failed.data["error_kind"], "internal_error")

    def test_output_limit_produces_no_output_event(self):
        engine = SericiteEngine()
        events = []
        with engine.observe(events.append):
            root = engine.create_root(
                'print("too long")',
                limits=SericiteLimits(max_output_bytes=2),
            )
            with self.assertRaises(SericiteError) as caught:
                root.run()
        self.assertEqual(caught.exception.kind, "resource_exhausted")
        self.assertFalse(any(event.kind == "vm.output" for event in events))
        self.assertEqual(events[-1].data["new_state"], "resource_exhausted")
        self.assertEqual(events[-1].data["error_kind"], "resource_exhausted")

    def test_forwarded_output_is_attributed_to_each_real_vm(self):
        engine = SericiteEngine()
        events = []
        with engine.observe(events.append):
            root = engine.create_root(
                "def forward(text):\n    print(text, end='')\n"
                "sub = VM('print(\"child\")', output_writer=forward)\n"
                "sub.run()"
            )
            root.run()
        output = [event for event in events if event.kind == "vm.output"]
        self.assertEqual(
            [(event.vm_id, event.data["text"]) for event in output],
            [(1, "child\n"), (0, "child\n")],
        )


class ObservationStateTests(unittest.TestCase):
    def test_breakpoint_pause_and_resume(self):
        engine = SericiteEngine()
        events = []
        with engine.observe(events.append):
            root = engine.create_root("x = 1\nx = 2")
            root.add_breakpoint(2)
            root.run()
            root.run()
        changes = [event for event in events if event.kind == "vm.state_changed"]
        self.assertEqual(
            [(event.data["new_state"], event.data["reason"]) for event in changes],
            [("paused", "breakpoint"), ("ready", "resume"), ("done", "return")],
        )
        self.assertEqual(changes[0].data["breakpoint"], {"line": 2, "path": None})

    def test_input_wait_and_feed(self):
        engine = SericiteEngine()
        events = []
        with engine.observe(events.append):
            root = engine.create_root("value = input()\nprint(value)")
            root.run()
            root.feed_input("ok")
            root.run()
        changes = [event for event in events if event.kind == "vm.state_changed"]
        self.assertEqual(
            [(event.data["new_state"], event.data["reason"]) for event in changes],
            [("waiting_input", "input"), ("ready", "input"), ("done", "return")],
        )

    def test_exec_rebinds_state_and_caught_errors_do_not_fail_vm(self):
        engine = SericiteEngine()
        events = []
        with engine.observe(events.append):
            root = engine.create_root("x = 1")
            root.run()
            events.clear()
            root.exec("y = 2")
            self.assertEqual(
                [
                    (
                        event.data["old_state"],
                        event.data["new_state"],
                        event.data["reason"],
                    )
                    for event in events
                    if event.kind == "vm.state_changed"
                ],
                [("done", "ready", "exec"), ("ready", "done", "return")],
            )
            events.clear()
            root.exec("try:\n    raise 'caught'\nexcept raise_error:\n    pass")
        self.assertEqual(
            [
                event.data["new_state"]
                for event in events
                if event.kind == "vm.state_changed"
            ],
            ["ready", "done"],
        )
        self.assertFalse(any(event.data.get("error_kind") for event in events))

    def test_terminal_error_contains_kind(self):
        engine = SericiteEngine()
        events = []
        with engine.observe(events.append):
            root = engine.create_root("raise 'boom'")
            with self.assertRaises(SericiteError):
                root.run()
        self.assertEqual(events[-1].kind, "vm.state_changed")
        self.assertEqual(events[-1].data["old_state"], "ready")
        self.assertEqual(events[-1].data["new_state"], "error")
        self.assertEqual(events[-1].data["error_kind"], "raise_error")


class ObservationIsolationTests(unittest.TestCase):
    def test_failed_sink_is_disabled_without_affecting_other_sinks_or_vm(self):
        engine = SericiteEngine()
        good_events = []
        calls = []

        def bad_sink(event):
            calls.append(event)
            if event.kind == "vm.output":
                raise RuntimeError("sink failed")

        bad = engine.observe(bad_sink)
        good = engine.observe(good_events.append)
        root = engine.create_root('print("still runs")')
        self.assertEqual(root.run(), "still runs\n")
        self.assertEqual(root.snapshot()["state"], "done")
        self.assertTrue(bad.failed)
        self.assertTrue(bad.closed)
        self.assertIn("RuntimeError: sink failed", bad.failure)
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [event.kind for event in good_events],
            ["vm.created", "vm.output", "vm.state_changed"],
        )
        good.close()

    def test_unprintable_sink_failure_is_contained_on_all_delivery_paths(self):
        class UnprintableError(RuntimeError):
            def __str__(self):
                raise ValueError("cannot format")

        created_engine = SericiteEngine()

        def fail_created(event):
            if event.kind == "vm.created":
                raise UnprintableError

        created = created_engine.observe(fail_created)
        root = created_engine.create_root("print('after')")
        self.assertEqual(root.run(), "after\n")
        self.assertEqual(root.snapshot()["state"], "done")
        self.assertTrue(created.closed)
        self.assertTrue(created.failed)
        self.assertEqual(created.failure, "UnprintableError")

        output_engine = SericiteEngine()

        def fail_output(event):
            if event.kind == "vm.output":
                raise UnprintableError

        output = output_engine.observe(fail_output)
        root = output_engine.create_root("print('first')\nprint('second')")
        self.assertEqual(root.run(), "first\nsecond\n")
        self.assertEqual(root.snapshot()["state"], "done")
        self.assertTrue(output.closed)
        self.assertEqual(output.failure, "UnprintableError")

        gc_engine = SericiteEngine()

        def fail_gc(event):
            if event.kind == "vm.disposed":
                raise UnprintableError

        collected = gc_engine.observe(fail_gc)
        root = gc_engine.create_root("def make():\n    sub = VM('')\nmake()")
        root.run()
        gc.collect()
        collected.poll()
        self.assertEqual(root.snapshot()["state"], "done")
        self.assertTrue(collected.closed)
        self.assertTrue(collected.failed)
        self.assertEqual(collected.failure, "UnprintableError")

    def test_closing_another_observer_stops_current_delivery(self):
        engine = SericiteEngine()
        first_events = []
        second_events = []
        second = None

        def close_second(event):
            first_events.append(event)
            second.close()

        first = engine.observe(close_second)
        second = engine.observe(second_events.append)
        engine.create_root("print('x')")
        self.assertTrue(second.closed)
        self.assertEqual(second_events, [])
        self.assertEqual([event.kind for event in first_events], ["vm.created"])
        first.close()

    def test_event_data_is_independent_between_observers(self):
        engine = SericiteEngine()
        second_events = []

        def forge(event):
            if event.kind == "vm.output":
                event.data["text"] = "forged"
            elif event.data.get("new_state") == "paused":
                event.data["breakpoint"]["line"] = 99

        first = engine.observe(forge)
        second = engine.observe(second_events.append)
        root = engine.create_root("x = 1\nprint('real')")
        root.add_breakpoint(2)
        root.run()
        self.assertEqual(root.stdout(), "")
        paused = [
            event for event in second_events if event.data.get("new_state") == "paused"
        ]
        self.assertEqual(paused[0].data["breakpoint"]["line"], 2)
        root.run()
        self.assertEqual(root.stdout(), "real\n")
        output = [event for event in second_events if event.kind == "vm.output"]
        self.assertEqual(output[0].data["text"], "real\n")
        first.close()
        second.close()

    def test_base_exception_from_sink_propagates_to_host(self):
        engine = SericiteEngine()
        observation = engine.observe(lambda event: None)

        def interrupt(event):
            if event.kind == "vm.output":
                raise KeyboardInterrupt

        observation.close()
        engine.observe(interrupt)
        root = engine.create_root("print('x')")
        with self.assertRaises(KeyboardInterrupt):
            root.run()

    def test_callback_reentry_is_rejected_and_close_is_allowed(self):
        engine = SericiteEngine()
        errors = []
        root = None
        fs = engine.create_vfs()
        observation = None

        def sink(event):
            if event.kind != "vm.output":
                return
            operations = (
                lambda: root.run(),
                lambda: root.dispose(),
                lambda: root.feed_input("x"),
                lambda: fs.write_file("/x", "x"),
                lambda: engine.create_vfs(),
                lambda: engine.create_root(""),
                lambda: engine.observe(lambda event: None),
                lambda: observation.poll(),
            )
            for operation in operations:
                try:
                    operation()
                except SericiteError as exc:
                    errors.append(exc.kind)
            observation.close()

        observation = engine.observe(sink)
        root = engine.create_root("print('x')")
        self.assertEqual(root.run(), "x\n")
        self.assertEqual(errors, ["runtime_error"] * 8)
        self.assertTrue(observation.closed)
        self.assertEqual(root.snapshot()["state"], "done")

    def test_observation_does_not_change_execution_accounts(self):
        source = 'sub = VM("x = 1\\nprint(x)")\nsub.run()'
        plain_engine = SericiteEngine()
        plain = plain_engine.create_root(source)
        plain.run()

        observed_engine = SericiteEngine()
        events = []
        with observed_engine.observe(events.append):
            observed = observed_engine.create_root(source)
            observed.run()
        self.assertEqual(
            observed.snapshot()["instruction_count"],
            plain.snapshot()["instruction_count"],
        )
        self.assertEqual(
            observed_engine._contexts[1].alloc_bytes,
            plain_engine._contexts[1].alloc_bytes,
        )


class ObservationGarbageCollectionTests(unittest.TestCase):
    def test_gc_notification_waits_for_poll(self):
        engine = SericiteEngine()
        events = []
        observation = engine.observe(events.append)
        root = engine.create_root("def make():\n    sub = VM('x = 1')\nmake()")
        root.run()
        gc.collect()

        self.assertEqual(set(engine._contexts), {0})
        self.assertFalse(any(event.kind == "vm.disposed" for event in events))
        observation.poll()
        disposed = [event for event in events if event.kind == "vm.disposed"]
        self.assertEqual(len(disposed), 1)
        self.assertEqual(disposed[0].vm_id, 1)
        self.assertEqual(disposed[0].parent_id, 0)
        self.assertEqual(disposed[0].data, {"reason": "gc", "state": "ready"})
        observation.close()

    def test_safe_engine_entry_flushes_gc_before_new_events(self):
        engine = SericiteEngine()
        events = []
        observation = engine.observe(events.append)
        root = engine.create_root("def make():\n    sub = VM('')\nmake()")
        root.run()
        gc.collect()
        events.clear()

        root.exec("print('next')")
        self.assertEqual(
            [event.kind for event in events],
            ["vm.disposed", "vm.state_changed", "vm.output", "vm.state_changed"],
        )
        self.assertEqual(events[0].data["reason"], "gc")
        self.assertEqual(
            [event.sequence for event in events],
            sorted(event.sequence for event in events),
        )
        observation.close()

    def test_late_and_closed_observers_do_not_receive_old_tombstones(self):
        engine = SericiteEngine()
        first_events = []
        first = engine.observe(first_events.append)
        root = engine.create_root("def make():\n    sub = VM('')\nmake()")
        root.run()
        gc.collect()

        second_events = []
        second = engine.observe(second_events.append)
        self.assertEqual(
            [event.kind for event in first_events if event.kind == "vm.disposed"],
            ["vm.disposed"],
        )
        self.assertEqual(second_events, [])
        first.close()
        second.close()

        root.exec("make()")
        gc.collect()
        third_events = []
        third = engine.observe(third_events.append)
        self.assertEqual(third_events, [])
        third.poll()
        self.assertEqual(third_events, [])
        third.close()

    def test_self_and_cross_vm_cycles_are_reported_after_collection(self):
        engine = SericiteEngine()
        events = []
        observation = engine.observe(events.append)
        root = engine.create_root(
            "def get_vm():\n    return vm_a\n"
            "vm_a = VM('self = get_vm()', functions={'get_vm': get_vm})\n"
            "vm_a.run()"
        )
        root.run()
        del root
        gc.collect()
        observation.poll()
        self.assertEqual(
            {event.vm_id for event in events if event.kind == "vm.disposed"},
            {0, 1},
        )

        root = engine.create_root(
            "def get_a():\n    return a\n"
            "def get_b():\n    return b\n"
            "a = VM('b = get_b()', functions={'get_b': get_b})\n"
            "b = VM('a = get_a()', functions={'get_a': get_a})\n"
            "a.run()\nb.run()"
        )
        root.run()
        del root
        gc.collect()
        observation.poll()
        collected = [
            event.vm_id
            for event in events
            if event.kind == "vm.disposed"
            and event.data["reason"] == "gc"
            and event.parent_id == 2
        ]
        self.assertEqual(set(collected), {3, 4})
        observation.close()

    def test_explicit_dispose_does_not_also_queue_gc_event(self):
        engine = SericiteEngine()
        events = []
        observation = engine.observe(events.append)
        root = engine.create_root('sub = VM("")\nsub.dispose()')
        root.run()
        gc.collect()
        observation.poll()
        disposed = [event for event in events if event.kind == "vm.disposed"]
        self.assertEqual(len(disposed), 1)
        self.assertEqual(disposed[0].data["reason"], "dispose")
        observation.close()

    def test_observed_gc_still_refunds_live_vm_quotas(self):
        engine = SericiteEngine(SericiteLimits(max_total_vms=2))
        events = []
        observation = engine.observe(events.append)
        root = engine.create_root("def make():\n    sub = VM('')")
        root.run()
        for _ in range(3):
            root.exec("make()")
            gc.collect()
            self.assertEqual(set(engine._contexts), {0})
            self.assertEqual(root.snapshot()["vm_id"], 0)
        observation.poll()
        self.assertEqual(root.snapshot()["child_count"], 3)
        self.assertEqual(root._context.live_descendant_count, 0)
        self.assertEqual(
            len([event for event in events if event.data.get("reason") == "gc"]),
            3,
        )
        observation.close()


class ObservationSnapshotTests(unittest.TestCase):
    def test_reads_grandchild_host_snapshot_without_returning_handle(self):
        engine = SericiteEngine()
        events = []
        grandchild_source = "x = 41\nprint(x)"
        child_source = f"grandchild = VM({grandchild_source!r})\ngrandchild.run()"
        with engine.observe(events.append) as observation:
            root = engine.create_root(f"child = VM({child_source!r})\nchild.run()")
            root.run()
            snapshot = observation.snapshot(2)
        self.assertEqual(snapshot["state"], "done")
        self.assertEqual(snapshot["locals"]["x"], 41)
        self.assertEqual(snapshot["stdout"], "41\n")
        self.assertEqual(snapshot["vm_id"], 2)
        self.assertEqual(snapshot["parent_id"], 1)
        self.assertEqual(snapshot["depth"], 2)

    def test_reads_paused_breakpoint_scene(self):
        engine = SericiteEngine()
        grandchild_source = "x = 1\nx = 2"
        child_source = (
            f"grandchild = VM({grandchild_source!r})\n"
            "grandchild.add_breakpoint(2)\ngrandchild.run()"
        )
        with engine.observe(lambda event: None) as observation:
            root = engine.create_root(f"child = VM({child_source!r})\nchild.run()")
            root.run()
            snapshot = observation.snapshot(2)
        self.assertEqual(snapshot["state"], "paused")
        self.assertEqual(snapshot["locals"]["x"], 1)
        self.assertEqual(snapshot["next_line"], 2)
        self.assertEqual(snapshot["breakpoint"], {"line": 2, "path": None})

    def test_callback_can_read_current_vm_snapshot(self):
        engine = SericiteEngine()
        snapshots = []
        observation = None

        def sink(event):
            if event.kind == "vm.output":
                snapshots.append(observation.snapshot(event.vm_id))

        observation = engine.observe(sink)
        root = engine.create_root("print('live')")
        self.assertEqual(root.run(), "live\n")
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["vm_id"], 0)
        self.assertEqual(snapshots[0]["stdout"], "live\n")
        observation.close()

    def test_breakpoint_callback_snapshot_matches_event(self):
        engine = SericiteEngine()
        scenes = []
        observation = None

        def sink(event):
            if event.data.get("new_state") == "paused":
                snapshot = observation.snapshot(event.vm_id)
                scenes.append((event.data["breakpoint"], snapshot))

        observation = engine.observe(sink)
        root = engine.create_root("x = 1\nx = 2")
        root.add_breakpoint(2)
        root.run()
        self.assertEqual(len(scenes), 1)
        event_breakpoint, snapshot = scenes[0]
        self.assertEqual(snapshot["state"], "paused")
        self.assertEqual(snapshot["breakpoint"], event_breakpoint)
        self.assertEqual(snapshot["locals"]["x"], 1)
        observation.close()

    def test_snapshot_preserves_descendant_error(self):
        engine = SericiteEngine()
        with engine.observe(lambda event: None) as observation:
            root = engine.create_root(
                "sub = VM(\"raise 'boom'\")\n"
                "try:\n    sub.run()\nexcept raise_error:\n    pass"
            )
            root.run()
            snapshot = observation.snapshot(1)
        self.assertEqual(snapshot["state"], "error")
        self.assertEqual(snapshot["error"]["kind"], "raise_error")

    def test_invalid_unknown_disposed_and_closed_snapshot_requests_fail(self):
        engine = SericiteEngine()
        observation = engine.observe(lambda event: None)
        root = engine.create_root("")
        for vm_id in (True, -1, 1.0, "0", None):
            with self.subTest(vm_id=vm_id), self.assertRaises(SericiteError) as caught:
                observation.snapshot(vm_id)
            self.assertEqual(caught.exception.kind, "type_error")
        with self.assertRaises(SericiteError) as caught:
            observation.snapshot(99)
        self.assertEqual(caught.exception.kind, "runtime_error")
        root.dispose()
        with self.assertRaises(SericiteError) as caught:
            observation.snapshot(0)
        self.assertEqual(caught.exception.kind, "runtime_error")
        observation.close()
        with self.assertRaises(SericiteError) as caught:
            observation.snapshot(0)
        self.assertEqual(caught.exception.kind, "runtime_error")

    def test_snapshot_does_not_retain_collected_vm(self):
        engine = SericiteEngine()
        events = []
        with engine.observe(events.append) as observation:
            root = engine.create_root("sub = VM('x = 1')")
            root.run()
            self.assertEqual(observation.snapshot(1)["locals"], {})
            root.exec("sub = None")
            gc.collect()
            observation.poll()
            self.assertEqual(set(engine._contexts), {0})
            with self.assertRaises(SericiteError) as caught:
                observation.snapshot(1)
            self.assertEqual(caught.exception.kind, "runtime_error")
        self.assertEqual(
            [event.data["reason"] for event in events if event.kind == "vm.disposed"],
            ["gc"],
        )


if __name__ == "__main__":
    unittest.main()
