from __future__ import annotations

from .models import Evidence, Finding, ManagementAction, ManagementPlan, TraceSummary
from .stats import fmt_ms


CONSTRAINTS = [
    "No runtime mutation in v0.2: the plan recommends policies but does not hook games, drivers, or OS schedulers.",
    "RAM/VRAM and texture residency actions are inferred from frame symptoms until direct memory telemetry is added.",
    "Every policy must be backed by trace evidence and mapped to a concrete future control surface.",
]


def build_management_plan(
    summary: TraceSummary, findings: list[Finding]
) -> ManagementPlan:
    actions = [
        action
        for action in (
            queue_depth_policy(summary, findings),
            cpu_gpu_handoff_policy(summary, findings),
            gpu_feeding_policy(summary, findings),
            frame_pacing_policy(summary, findings),
            memory_residency_policy(summary, findings),
            presentation_path_policy(summary, findings),
        )
        if action is not None
    ]
    actions = sorted(actions, key=lambda action: action.priority, reverse=True)[:8]
    target = summary.application or "Unknown"
    return ManagementPlan(
        mode="advisory-management-v0.2",
        target=target,
        summary=plan_summary(actions),
        actions=actions,
        constraints=CONSTRAINTS,
    )


def queue_depth_policy(
    summary: TraceSummary, findings: list[Finding]
) -> ManagementAction | None:
    finding = find(findings, "cpu-present-wait")
    if not finding:
        return None
    metric = summary.metrics.get("MsInPresentAPI")
    return ManagementAction(
        id="adaptive-frame-queue-depth",
        title="Adaptive frame queue depth",
        layer="CPU/GPU/display scheduler",
        objective="Keep the CPU producing useful work without allowing excess present queue latency.",
        policy=(
            "Future runtime should monitor Present() blocking and dynamically cap or relax "
            "frame queue depth before the CPU reaches late synchronization."
        ),
        trigger="High MsCPUWait or MsInPresentAPI relative to the typical frame time.",
        expected_effect="Lower input-to-display latency and fewer CPU-side stalls.",
        risk="Too aggressive queue reduction can underfeed the GPU on bursty workloads.",
        priority=priority_from_finding(finding, 8),
        confidence=finding.confidence,
        source_findings=[finding.id],
        evidence=[
            Evidence(
                "MsInPresentAPI p95",
                fmt_ms(metric.p95 if metric else None),
                "Present() blocking is the primary signal for queue-depth control.",
            ),
            *finding.evidence[:2],
        ],
    )


def cpu_gpu_handoff_policy(
    summary: TraceSummary, findings: list[Finding]
) -> ManagementAction | None:
    wait = find(findings, "cpu-present-wait")
    bubbles = find(findings, "gpu-bubbles")
    if not wait and not bubbles:
        return None
    source = [finding.id for finding in (wait, bubbles) if finding]
    priority = max(priority_from_finding(finding, 0) for finding in (wait, bubbles) if finding)
    cpu_wait = summary.metrics.get("MsCPUWait")
    gpu_wait = summary.metrics.get("MsGPUWait")
    return ManagementAction(
        id="early-handoff-scheduler",
        title="Early CPU/GPU handoff scheduler",
        layer="CPU/GPU work submission",
        objective="Move synchronization decisions earlier so the GPU receives work before the frame path becomes idle.",
        policy=(
            "Future runtime should classify frames as CPU-late, GPU-late, or display-late, "
            "then bias task ordering toward the stage that is about to starve."
        ),
        trigger="CPU wait or GPU wait spikes in the same capture window.",
        expected_effect="Fewer idle gaps between CPU submission, GPU execution, and presentation.",
        risk="Requires engine/API integration or interception to act instead of only diagnose.",
        priority=priority + 4,
        confidence=combined_confidence(wait, bubbles),
        source_findings=source,
        evidence=[
            Evidence(
                "MsCPUWait p95",
                fmt_ms(cpu_wait.p95 if cpu_wait else None),
                "CPU wait signal used to detect late synchronization.",
            ),
            Evidence(
                "MsGPUWait p95",
                fmt_ms(gpu_wait.p95 if gpu_wait else None),
                "GPU wait signal used to detect starvation or bubbles.",
            ),
        ],
    )


def gpu_feeding_policy(
    summary: TraceSummary, findings: list[Finding]
) -> ManagementAction | None:
    finding = find(findings, "gpu-bubbles")
    if not finding:
        return None
    gpu_wait = summary.metrics.get("MsGPUWait")
    gpu_time = summary.metrics.get("MsGPUTime")
    return ManagementAction(
        id="gpu-work-prefetch-budget",
        title="GPU work prefetch budget",
        layer="GPU command scheduling",
        objective="Keep command buffers and upload work ready before GPU execution windows go idle.",
        policy=(
            "Future runtime should reserve a small pre-submit budget for command buffer preparation, "
            "resource transitions, and upload scheduling when GPU wait rises."
        ),
        trigger="High GPU wait relative to GPU work time or frame time.",
        expected_effect="Reduced GPU bubbles and better useful work per watt.",
        risk="Prefetching the wrong work can increase memory pressure or wasted uploads.",
        priority=priority_from_finding(finding, 6),
        confidence=finding.confidence,
        source_findings=[finding.id],
        evidence=[
            Evidence(
                "MsGPUWait p95",
                fmt_ms(gpu_wait.p95 if gpu_wait else None),
                "Primary starvation signal.",
            ),
            Evidence(
                "MsGPUTime p95",
                fmt_ms(gpu_time.p95 if gpu_time else None),
                "Baseline GPU work duration.",
            ),
        ],
    )


def frame_pacing_policy(
    summary: TraceSummary, findings: list[Finding]
) -> ManagementAction | None:
    finding = find(findings, "unstable-frame-pacing")
    if not finding:
        return None
    between = summary.metrics.get("MsBetweenPresents")
    return ManagementAction(
        id="pacing-stability-controller",
        title="Frame pacing stability controller",
        layer="Presentation scheduler",
        objective="Favor stable delivery over raw average throughput when pacing variance is high.",
        policy=(
            "Future runtime should detect unstable pacing windows and temporarily bias scheduling "
            "toward deterministic present cadence, upload pacing, and queue smoothing."
        ),
        trigger="High stdev/p50 or p99/p50 in frame presentation timing.",
        expected_effect="Less visible stutter and fewer burst-driven synchronization cascades.",
        risk="Stability policies may cap peaks and reduce benchmark FPS while improving perceived smoothness.",
        priority=priority_from_finding(finding, 7),
        confidence=finding.confidence,
        source_findings=[finding.id],
        evidence=[
            Evidence(
                "MsBetweenPresents p99",
                fmt_ms(between.p99 if between else None),
                "Long-tail frame timing signal.",
            ),
            Evidence(
                "MsBetweenPresents stdev",
                fmt_ms(between.stdev if between else None),
                "Pacing variance signal.",
            ),
        ],
    )


def memory_residency_policy(
    summary: TraceSummary, findings: list[Finding]
) -> ManagementAction | None:
    sources = [
        finding
        for finding in findings
        if finding.id in {
            "gpu-bubbles",
            "unstable-frame-pacing",
            "excessive-presentation-latency",
            "undisplayed-frames",
        }
    ]
    if not sources:
        return None
    source_ids = [finding.id for finding in sources]
    strongest = max(sources, key=lambda finding: finding.score)
    gpu_wait = summary.metrics.get("MsGPUWait")
    pacing = summary.metrics.get("MsBetweenPresents")
    return ManagementAction(
        id="ram-vram-residency-manager",
        title="RAM/VRAM residency manager",
        layer="RAM/VRAM/resource residency",
        objective="Reduce redundant movement of textures, buffers, staging data, and frame resources.",
        policy=(
            "Future runtime should score resources by reuse probability, upload urgency, and frame-criticality, "
            "then keep hot resources resident while delaying or coalescing cold transfers."
        ),
        trigger=(
            "GPU bubbles, pacing spikes, excessive latency, or undisplayed work that may indicate "
            "resource movement happening at the wrong time."
        ),
        expected_effect="Fewer late uploads, fewer redundant staging copies, and lower memory-traffic pressure.",
        risk=(
            "PresentMon alone cannot prove RAM/VRAM cause; direct memory telemetry must be added "
            "before automatic residency control."
        ),
        priority=priority_from_finding(strongest, 2),
        confidence="medium" if len(sources) >= 2 else "low",
        source_findings=source_ids,
        evidence=[
            Evidence(
                "Correlated findings",
                str(len(sources)),
                "Number of frame-path symptoms that can be consistent with bad resource residency.",
            ),
            Evidence(
                "MsGPUWait p95",
                fmt_ms(gpu_wait.p95 if gpu_wait else None),
                "Indirect signal for late GPU work or missing resources.",
            ),
            Evidence(
                "MsBetweenPresents p99",
                fmt_ms(pacing.p99 if pacing else None),
                "Indirect signal for transfer or residency-driven frame spikes.",
            ),
        ],
    )


def presentation_path_policy(
    summary: TraceSummary, findings: list[Finding]
) -> ManagementAction | None:
    sources = [
        finding
        for finding in findings
        if finding.id in {"presentation-copy-path", "composition-waste"}
    ]
    if not sources:
        return None
    source_ids = [finding.id for finding in sources]
    strongest = max(sources, key=lambda finding: finding.score)
    latency = summary.metrics.get("DisplayLatency")
    return ManagementAction(
        id="zero-copy-presentation-route",
        title="Zero-copy presentation route preference",
        layer="Swap chain/display path",
        objective="Prefer presentation paths that avoid redundant copies and avoid late compositor work.",
        policy=(
            "Future runtime should rank presentation modes by copy risk and latency, then recommend "
            "or negotiate the least wasteful route available to the game/API context."
        ),
        trigger="Copy/GDI/composed presentation modes with latency or pacing symptoms.",
        expected_effect="Lower display path latency and fewer frame-buffer copies before scanout.",
        risk="Some presentation routes are constrained by OS, overlays, anti-cheat, window mode, and driver policy.",
        priority=priority_from_finding(strongest, 5),
        confidence=strongest.confidence,
        source_findings=source_ids,
        evidence=[
            Evidence(
                "Present modes",
                ", ".join(summary.present_modes) if summary.present_modes else "n/a",
                "Observed presentation path candidates.",
            ),
            Evidence(
                "DisplayLatency p95",
                fmt_ms(latency.p95 if latency else None),
                "Display path latency signal.",
            ),
        ],
    )


def find(findings: list[Finding], finding_id: str) -> Finding | None:
    for finding in findings:
        if finding.id == finding_id:
            return finding
    return None


def priority_from_finding(finding: Finding, bonus: int) -> int:
    return max(0, min(100, finding.score + bonus))


def combined_confidence(*findings: Finding | None) -> str:
    present = [finding for finding in findings if finding is not None]
    if len(present) >= 2:
        return "high"
    if present:
        return present[0].confidence
    return "low"


def plan_summary(actions: list[ManagementAction]) -> str:
    if not actions:
        return (
            "No management policies were activated. The trace does not contain enough "
            "strong signals for the v0.2 advisory manager."
        )
    layers = sorted({action.layer for action in actions})
    return (
        f"{len(actions)} advisory management policies activated across "
        f"{len(layers)} layers: {', '.join(layers)}."
    )
