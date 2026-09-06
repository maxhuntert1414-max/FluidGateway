from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .control import ControllerResult
from .runtime import RuntimeResource, nonnegative_number


DEFAULT_FRAME_BUDGET_MS = 16.67


@dataclass(frozen=True)
class PolicyEvidence:
    label: str
    value: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "value": self.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RuntimePolicyAction:
    id: str
    title: str
    scope: str
    severity: str
    confidence: str
    frame: int | None
    policy: str
    rationale: str
    recommendation: str
    evidence: list[PolicyEvidence]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "scope": self.scope,
            "severity": self.severity,
            "confidence": self.confidence,
            "frame": self.frame,
            "policy": self.policy,
            "rationale": self.rationale,
            "recommendation": self.recommendation,
            "evidence": [item.to_dict() for item in self.evidence],
        }


class RuntimePolicyEngine:
    """Frame and memory policy layer above the low-level decision engine."""

    def __init__(self) -> None:
        self.target_frame_ms = DEFAULT_FRAME_BUDGET_MS
        self.memory_budgets_mb: dict[str, float] = {}
        self.active_resources: dict[str, RuntimeResource] = {}
        self.memory_totals_mb: dict[str, float] = {}
        self.actions: list[RuntimePolicyAction] = []
        self._emitted: set[tuple[str, int | None, str]] = set()

    def configure(self, payload: dict[str, Any]) -> None:
        target_frame_ms = first_number(
            payload,
            "target_frame_ms",
            "frame_budget_ms",
            "budget_ms",
        )
        budgets = payload.get("budgets")
        if isinstance(budgets, dict):
            target_frame_ms = target_frame_ms or number_value(budgets.get("frame_ms"))
            for memory in ("ram", "vram", "shared", "staging", "swapchain"):
                value = number_value(budgets.get(f"{memory}_mb"))
                if value is not None:
                    self.memory_budgets_mb[memory] = value

        if target_frame_ms is not None:
            self.target_frame_ms = target_frame_ms

        for memory in ("ram", "vram", "shared", "staging", "swapchain"):
            value = first_number(payload, f"{memory}_budget_mb", f"{memory}_mb")
            if value is not None:
                self.memory_budgets_mb[memory] = value

    def frame_budget_from(self, payload: dict[str, Any]) -> float:
        return (
            first_number(payload, "target_frame_ms", "frame_budget_ms", "budget_ms")
            or self.target_frame_ms
        )

    def register_resource(
        self, resource: RuntimeResource, frame: int | None
    ) -> list[RuntimePolicyAction]:
        self.active_resources[resource.id] = resource
        self._recalculate_memory_totals()
        return self._check_memory_budget(resource.memory, frame)

    def release_resource(self, resource_id: str) -> None:
        self.active_resources.pop(resource_id, None)
        self._recalculate_memory_totals()

    def record_operation(
        self,
        result: ControllerResult,
        frame: int | None,
        target_frame_ms: float,
    ) -> list[RuntimePolicyAction]:
        operation = result.operation
        if not result.executed:
            return []
        if operation.type not in {"copy", "upload"}:
            return []
        threshold = max(1.0, target_frame_ms * 0.20)
        if operation.cost_ms < threshold:
            return []
        emitted = self._emit_once(
            RuntimePolicyAction(
                id="late-upload-pressure",
                title="Late transfer pressure inside frame",
                scope="frame-transfer",
                severity="high"
                if operation.cost_ms >= target_frame_ms * 0.50
                else "medium",
                confidence="medium",
                frame=frame,
                policy="schedule-large-transfers-before-frame-critical-work",
                rationale=(
                    "A copy/upload operation consumes a large slice of the current frame budget."
                ),
                recommendation=(
                    "Move predictable uploads earlier, keep hot resources resident, or split the transfer before draw-critical work."
                ),
                evidence=[
                    PolicyEvidence(
                        "Transfer cost",
                        f"{operation.cost_ms:.4f} ms",
                        "Measured cost submitted by the adapter for this operation.",
                    ),
                    PolicyEvidence(
                        "Frame budget",
                        f"{target_frame_ms:.4f} ms",
                        "Target budget configured for the active frame/session.",
                    ),
                    PolicyEvidence(
                        "Transfer size",
                        f"{operation.size_mb:.4f} MB",
                        "Amount of data moved by the operation.",
                    ),
                ],
            ),
            frame,
            operation.id,
        )
        return [] if emitted is None else [emitted]

    def finish_frame(
        self,
        frame: int,
        target_frame_ms: float,
        estimated_total_cost_ms: float,
        queue_costs: dict[str, float],
    ) -> list[RuntimePolicyAction]:
        actions: list[RuntimePolicyAction] = []
        if estimated_total_cost_ms > target_frame_ms:
            emitted = self._emit_once(
                RuntimePolicyAction(
                    id="frame-budget-pressure",
                    title="Frame work exceeds target budget",
                    scope="frame-budget",
                    severity="high"
                    if estimated_total_cost_ms >= target_frame_ms * 1.50
                    else "medium",
                    confidence="medium",
                    frame=frame,
                    policy="budget-frame-work-before-execution",
                    rationale=(
                        "The submitted work for this frame is heavier than the configured frame budget."
                    ),
                    recommendation=(
                        "Defer non-critical uploads/compute, reduce queue depth, or move preparation to an earlier frame."
                    ),
                    evidence=[
                        PolicyEvidence(
                            "Estimated frame work",
                            f"{estimated_total_cost_ms:.4f} ms",
                            "Sum of executed operation costs observed for the frame.",
                        ),
                        PolicyEvidence(
                            "Target frame budget",
                            f"{target_frame_ms:.4f} ms",
                            "Configured frame budget.",
                        ),
                    ],
                ),
                frame,
                "frame-budget",
            )
            if emitted is not None:
                actions.append(emitted)

        if queue_costs:
            busiest_queue, busiest_cost = max(queue_costs.items(), key=lambda item: item[1])
            if busiest_cost > target_frame_ms * 0.75 and len(queue_costs) > 1:
                emitted = self._emit_once(
                    RuntimePolicyAction(
                        id="queue-imbalance-pressure",
                        title="One queue dominates the frame budget",
                        scope="queue-budget",
                        severity="medium",
                        confidence="low",
                        frame=frame,
                        policy="rebalance-frame-work-across-queues",
                        rationale=(
                            "One queue consumes most of the frame budget while other queues also receive work."
                        ),
                        recommendation=(
                            "Move independent work earlier or spread it across available queues when dependencies allow."
                        ),
                        evidence=[
                            PolicyEvidence(
                                "Busiest queue",
                                busiest_queue,
                                "Queue with the highest observed operation cost.",
                            ),
                            PolicyEvidence(
                                "Busiest queue cost",
                                f"{busiest_cost:.4f} ms",
                                "Observed operation cost on the busiest queue.",
                            ),
                        ],
                    ),
                    frame,
                    busiest_queue,
                )
                if emitted is not None:
                    actions.append(emitted)
        return actions

    def _check_memory_budget(
        self, memory: str, frame: int | None
    ) -> list[RuntimePolicyAction]:
        budget = self.memory_budgets_mb.get(memory)
        total = self.memory_totals_mb.get(memory, 0.0)
        if budget is None or total <= budget:
            return []
        action_id = f"{memory}-budget-pressure"
        action = RuntimePolicyAction(
            id=action_id,
            title=f"{memory.upper()} residency exceeds configured budget",
            scope=f"{memory}-residency",
            severity="high" if total >= budget * 1.25 else "medium",
            confidence="medium",
            frame=frame,
            policy="reduce-or-defer-resource-residency",
            rationale=(
                "Active resources in this memory layer exceed the budget declared by the adapter."
            ),
            recommendation=(
                "Release transient resources earlier, avoid duplicate residency, or defer non-critical uploads."
            ),
            evidence=[
                PolicyEvidence(
                    "Active residency",
                    f"{total:.4f} MB",
                    f"Total active resource size currently registered in {memory}.",
                ),
                PolicyEvidence(
                    "Configured budget",
                    f"{budget:.4f} MB",
                    f"Budget declared for {memory}.",
                ),
            ],
        )
        emitted = self._emit_once(action, frame, memory)
        return [] if emitted is None else [emitted]

    def _emit_once(
        self, action: RuntimePolicyAction, frame: int | None, key: str
    ) -> RuntimePolicyAction | None:
        dedupe_key = (action.id, frame, key)
        if dedupe_key in self._emitted:
            return None
        self._emitted.add(dedupe_key)
        self.actions.append(action)
        return action

    def _recalculate_memory_totals(self) -> None:
        totals: dict[str, float] = {}
        for resource in self.active_resources.values():
            totals[resource.memory] = totals.get(resource.memory, 0.0) + resource.size_mb
        self.memory_totals_mb = totals


def first_number(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = number_value(payload.get(key))
        if value is not None:
            return value
    return None


def number_value(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return nonnegative_number(value, "budget")
    except ValueError:
        return None
