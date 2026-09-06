import unittest

from fluidgateway.adapter import RuntimeAdapterSession
from fluidgateway.control import FluidGatewayController
from fluidgateway.policy import RuntimePolicyEngine
from fluidgateway.runtime import RuntimeManifest, optimize_manifest, parse_operation, parse_resource


class RuntimeProvenanceTests(unittest.TestCase):
    def plans(self, operations):
        controller = FluidGatewayController()
        for name in ("source", "target", "other", "source_alias", "target_alias"):
            controller.register_resource(name, "buffer", "ram", size_mb=1,
                                         aliases=[name.removesuffix("_alias")])
        parsed = [parse_operation({"frame": 1, "size_mb": 1, **item}) for item in operations]
        manifest = optimize_manifest(RuntimeManifest("regression", controller.resources, parsed))
        results = []
        for op in parsed:
            payload = op.to_dict()
            payload["operation_id"] = payload.pop("id")
            payload["operation_type"] = payload.pop("type")
            results.append(controller.submit_operation(**payload))
        return manifest, results

    def test_writes_invalidate_copy_provenance_in_both_entrypoints(self):
        for kind in ("compute", "draw", "allocate", "upload", "copy"):
            for target in ("source", "target", "source_alias", "target_alias", None):
                with self.subTest(kind=kind, target=target):
                    plan, results = self.plans([
                        {"id": "first", "type": "copy", "source": "source", "target": "target"},
                        {"id": "write", "type": kind, "source": "other", "target": target},
                        {"id": "second", "type": "copy", "source": "source", "target": "target"},
                    ])
                    self.assertIn("second", [op.id for op in plan.kept_operations])
                    self.assertTrue(results[-1].executed)

    def test_copy_identity_does_not_cross_frames_or_queues(self):
        for changes in ({"frame": 2}, {"queue": "graphics"}):
            with self.subTest(changes=changes):
                plan, results = self.plans([
                    {"id": "first", "type": "copy", "source": "source", "target": "target", "queue": "copy"},
                    {"id": "second", "type": "copy", "source": "source", "target": "target", "queue": "copy", **changes},
                ])
                self.assertEqual(2, len(plan.kept_operations))
                self.assertTrue(results[-1].executed)

    def test_missing_or_unknown_endpoints_are_not_self_copies(self):
        for endpoint in (None, "unknown"):
            with self.subTest(endpoint=endpoint):
                plan, results = self.plans([
                    {"id": "copy", "type": "copy", "source": endpoint, "target": endpoint},
                ])
                self.assertEqual([], plan.decisions)
                self.assertTrue(results[0].executed)

    def test_duplicate_wait_is_redirected_to_retained_transfer(self):
        plan, results = self.plans([
            {"id": "first", "type": "copy", "source": "source", "target": "target"},
            {"id": "second", "type": "copy", "source": "source", "target": "target"},
            {"id": "wait", "type": "sync", "depends_on": ["second"], "cost_ms": 1},
            {"id": "draw", "type": "draw", "depends_on": ["second", "wait"]},
        ])
        self.assertEqual(["first", "wait", "draw"], [op.id for op in plan.kept_operations])
        self.assertEqual(["first"], plan.kept_operations[1].depends_on)
        self.assertEqual(["first", "wait"], plan.kept_operations[2].depends_on)
        self.assertTrue(results[2].executed)
        self.assertEqual(["first"], results[2].operation.depends_on)

    def test_release_and_reregister_invalidates_copies_and_allocations(self):
        for released in ("source", "target"):
            with self.subTest(released=released):
                session = RuntimeAdapterSession()
                for name in ("source", "target"):
                    session.process_event({"event": "resource", "id": name, "size_mb": 1})
                session.process_event({"event": "operation", "id": "alloc1", "op": "allocate",
                                       "target": "target", "size_mb": 1, "reason": "transient"})
                copy = {"event": "operation", "op": "copy", "source": "source", "target": "target", "size_mb": 1}
                session.process_event({**copy, "id": "first"})
                session.process_event({"event": "resource", "action": "release", "id": released})
                session.process_event({"event": "resource", "id": released, "size_mb": 1})
                response = session.process_event({**copy, "id": "second"})
                self.assertTrue(response["result"]["executed"])
                if released == "target":
                    result = session.process_event({"event": "operation", "id": "alloc2", "op": "allocate",
                                                    "target": "target", "size_mb": 1, "reason": "transient"})
                    self.assertTrue(result["result"]["executed"])

    def test_nonfinite_or_negative_runtime_numbers_are_rejected(self):
        for value in (float("nan"), float("inf"), -1, True, 10 ** 400):
            for key in ("cost_ms", "size_mb"):
                with self.subTest(value=str(value), key=key):
                    with self.assertRaises(ValueError):
                        parse_operation({"id": "bad", key: value})
            with self.assertRaises(ValueError):
                parse_resource({"id": "bad", "size_mb": value})

    def test_invalid_budgets_do_not_poison_policy_state(self):
        for value in (float("nan"), float("inf"), -1, True, 10 ** 400):
            with self.subTest(value=str(value)):
                policy = RuntimePolicyEngine()
                policy.configure({"target_frame_ms": value, "budgets": {"ram_mb": value}})
                self.assertEqual(16.67, policy.target_frame_ms)
                self.assertEqual({}, policy.memory_budgets_mb)

    def test_allocation_resize_cannot_reuse_obsolete_size(self):
        plan, results = self.plans([
            {"id": "small", "type": "allocate", "target": "target", "size_mb": 1},
            {"id": "large", "type": "allocate", "target": "target", "size_mb": 2},
            {"id": "small_again", "type": "allocate", "target": "target", "size_mb": 1, "reason": "transient"},
        ])
        self.assertEqual([], plan.decisions)
        self.assertTrue(results[-1].executed)

    def test_duplicate_operation_ids_are_rejected_without_overwriting_provenance(self):
        controller = FluidGatewayController()
        controller.submit_operation("same", "compute")
        with self.assertRaises(ValueError):
            controller.submit_operation("same", "compute")
        self.assertEqual(1, len(controller.executed_operations))

    def test_removed_work_keeps_its_other_dependencies(self):
        plan, results = self.plans([
            {"id": "dependency", "type": "compute"},
            {"id": "self", "type": "copy", "source": "target", "target": "target", "depends_on": ["dependency"]},
            {"id": "wait", "type": "sync", "depends_on": ["self"], "cost_ms": 1},
        ])
        self.assertEqual(["dependency", "wait"], [op.id for op in plan.kept_operations])
        self.assertEqual(["dependency"], results[-1].operation.depends_on)
