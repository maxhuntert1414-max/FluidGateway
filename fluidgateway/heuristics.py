from __future__ import annotations

from .models import Evidence, Finding, FrameSample, TraceSummary
from .stats import fmt_ms, fmt_percent, fmt_ratio, frame_numbers, percentile, ratio, stdev


def run_heuristics(frames: list[FrameSample], summary: TraceSummary) -> list[Finding]:
    target_ms = target_frame_ms(summary)
    findings = [
        item
        for item in (
            suspicious_copy_path(frames),
            excessive_presentation_latency(summary, target_ms),
            cpu_present_wait(frames, summary, target_ms),
            gpu_bubbles(summary, target_ms),
            unstable_frame_pacing(summary, target_ms),
            undisplayed_frames(frames),
            composition_waste(frames, summary, target_ms),
        )
        if item is not None
    ]
    return sorted(findings, key=lambda finding: finding.score, reverse=True)[:7]


def target_frame_ms(summary: TraceSummary) -> float:
    for metric in ("MsBetweenPresents", "DisplayedTime"):
        value = summary.metrics.get(metric)
        if value and value.p50 and value.p50 > 0:
            return value.p50
    return 16.67


def suspicious_copy_path(frames: list[FrameSample]) -> Finding | None:
    modes = [frame.present_mode for frame in frames if frame.present_mode]
    if not modes:
        return None

    suspicious = [
        mode
        for mode in modes
        if any(token in mode.lower() for token in ("copy", "cpu gdi", "gpu gdi"))
    ]
    if not suspicious:
        return None

    share = len(suspicious) / len(modes)
    score = clamp_score(45 + share * 45)
    common = most_common(suspicious)
    return Finding(
        id="presentation-copy-path",
        title="Presentation copy path suspeito",
        hypothesis=(
            "O caminho de apresentacao parece depender de copia ou GDI em uma "
            "parte relevante dos frames."
        ),
        severity=severity(score),
        confidence=confidence_from_share(share),
        score=score,
        evidence=[
            Evidence(
                "Frames suspeitos",
                f"{len(suspicious)} / {len(modes)}",
                "Frames cujo PresentMode contem Copy, CPU GDI ou GPU GDI.",
            ),
            Evidence(
                "Modo dominante",
                common,
                "Modo de apresentacao suspeito mais frequente.",
            ),
            Evidence(
                "Participacao",
                fmt_percent(share),
                "Quanto maior a participacao, maior a chance de transporte redundante.",
            ),
        ],
        recommendation=(
            "Investigue swap chain flip model, modo de tela, composicao do DWM e "
            "qualquer caminho que force copia antes da apresentacao."
        ),
    )


def excessive_presentation_latency(
    summary: TraceSummary, target_ms: float
) -> Finding | None:
    candidates = []
    for metric in ("DisplayLatency", "MsUntilDisplayed", "MsRenderPresentLatency"):
        metric_summary = summary.metrics.get(metric)
        if metric_summary and metric_summary.p95 is not None:
            candidates.append((metric, metric_summary.p95, ratio(metric_summary.p95, target_ms)))

    candidates = [item for item in candidates if item[2] is not None]
    if not candidates:
        return None

    metric, p95, latency_ratio = max(candidates, key=lambda item: item[2] or 0)
    if latency_ratio is None or (latency_ratio < 1.5 and p95 < target_ms + 8):
        return None

    score = clamp_score(35 + latency_ratio * 20)
    return Finding(
        id="excessive-presentation-latency",
        title="Latencia de apresentacao excessiva",
        hypothesis=(
            "O frame parece ficar tempo demais entre renderizacao, fila de "
            "apresentacao e chegada ao display."
        ),
        severity=severity(score),
        confidence="high" if len(candidates) >= 2 else "medium",
        score=score,
        evidence=[
            Evidence(
                "Metrica principal",
                metric,
                "Metrica com maior proporcao contra o tempo tipico de frame.",
            ),
            Evidence(
                "p95 observado",
                fmt_ms(p95),
                "Percentil 95 da latencia detectada.",
            ),
            Evidence(
                "Tempo tipico de frame",
                fmt_ms(target_ms),
                "Base estimada a partir de MsBetweenPresents ou DisplayedTime.",
            ),
            Evidence(
                "Razao",
                fmt_ratio(latency_ratio),
                "Quanto a latencia p95 excede o tempo tipico de frame.",
            ),
        ],
        recommendation=(
            "Compare modo de apresentacao, VSync, fila de frames e composicao. "
            "Se possivel, correlacione com GPUView/PIX para localizar a espera."
        ),
    )


def cpu_present_wait(
    frames: list[FrameSample], summary: TraceSummary, target_ms: float
) -> Finding | None:
    cpu_wait = summary.metrics.get("MsCPUWait")
    present_api = summary.metrics.get("MsInPresentAPI")
    wait_ratio = ratio(cpu_wait.p95 if cpu_wait else None, target_ms)
    present_ratio = ratio(present_api.p95 if present_api else None, target_ms)
    strongest = max(wait_ratio or 0, present_ratio or 0)

    if strongest < 0.35:
        return None

    sync_values = frame_numbers(frames, "SyncInterval")
    sync_share = None
    if sync_values:
        sync_share = len([value for value in sync_values if value > 0]) / len(sync_values)

    score = clamp_score(30 + strongest * 35 + (sync_share or 0) * 12)
    return Finding(
        id="cpu-present-wait",
        title="CPU esperando demais no caminho de apresentacao",
        hypothesis=(
            "A CPU parece passar uma fatia alta do frame esperando ou bloqueada "
            "perto de Present(), sugerindo sincronizacao tardia ou fila cheia."
        ),
        severity=severity(score),
        confidence="high" if cpu_wait and present_api else "medium",
        score=score,
        evidence=[
            Evidence(
                "MsCPUWait p95",
                fmt_ms(cpu_wait.p95 if cpu_wait else None),
                "Tempo de espera da CPU antes do proximo frame.",
            ),
            Evidence(
                "MsInPresentAPI p95",
                fmt_ms(present_api.p95 if present_api else None),
                "Tempo gasto dentro da chamada Present().",
            ),
            Evidence(
                "SyncInterval > 0",
                fmt_percent(sync_share),
                "Participacao de frames com sincronizacao solicitada pela aplicacao.",
            ),
            Evidence(
                "Maior razao vs frame",
                fmt_ratio(strongest),
                "Maior proporcao entre espera observada e tempo tipico de frame.",
            ),
        ],
        recommendation=(
            "Verifique VSync, frame queue, limite de FPS e pontos onde a CPU "
            "espera a GPU/display antes de iniciar trabalho util do proximo frame."
        ),
    )


def gpu_bubbles(summary: TraceSummary, target_ms: float) -> Finding | None:
    gpu_wait = summary.metrics.get("MsGPUWait")
    gpu_time = summary.metrics.get("MsGPUTime")
    gpu_busy = summary.metrics.get("MsGPUBusy")
    wait_p95 = gpu_wait.p95 if gpu_wait else None
    time_p95 = gpu_time.p95 if gpu_time else None
    busy_p95 = gpu_busy.p95 if gpu_busy else None
    wait_vs_frame = ratio(wait_p95, target_ms)
    wait_vs_time = ratio(wait_p95, time_p95 or busy_p95)

    if (wait_vs_frame or 0) < 0.25 and (wait_vs_time or 0) < 0.40:
        return None

    score = clamp_score(35 + (wait_vs_frame or 0) * 35 + min(wait_vs_time or 0, 3) * 12)
    return Finding(
        id="gpu-bubbles",
        title="GPU subalimentada ou com bolhas",
        hypothesis=(
            "A GPU parece ter janelas de ociosidade dentro do trabalho do frame, "
            "o que pode indicar dependencia CPU/GPU, filas ruins ou sync prematuro."
        ),
        severity=severity(score),
        confidence="high" if gpu_wait and (gpu_time or gpu_busy) else "medium",
        score=score,
        evidence=[
            Evidence(
                "MsGPUWait p95",
                fmt_ms(wait_p95),
                "Tempo p95 em que a GPU ficou sem trabalho util para o frame.",
            ),
            Evidence(
                "MsGPUTime p95",
                fmt_ms(time_p95),
                "Tempo total p95 de trabalho de GPU por frame.",
            ),
            Evidence(
                "MsGPUBusy p95",
                fmt_ms(busy_p95),
                "Tempo p95 em que algum motor da GPU estava executando trabalho alvo.",
            ),
            Evidence(
                "Wait / frame",
                fmt_ratio(wait_vs_frame),
                "Quanto a espera de GPU representa do frame tipico.",
            ),
        ],
        recommendation=(
            "Procure barreiras, dependencia de upload, workloads serializados e "
            "pontos onde a CPU entrega trabalho tarde demais para a GPU."
        ),
    )


def unstable_frame_pacing(summary: TraceSummary, target_ms: float) -> Finding | None:
    between = summary.metrics.get("MsBetweenPresents")
    displayed = summary.metrics.get("DisplayedTime")
    animation = summary.metrics.get("MsAnimationError")

    between_jitter = ratio(between.stdev if between else None, between.p50 if between else None)
    displayed_jitter = ratio(
        displayed.stdev if displayed else None,
        displayed.p50 if displayed else None,
    )
    p99_ratio = ratio(between.p99 if between else None, between.p50 if between else None)
    animation_p95 = animation.p95 if animation else None
    animation_ratio = ratio(animation_p95, target_ms)
    strongest = max(
        between_jitter or 0,
        displayed_jitter or 0,
        (p99_ratio or 1) - 1,
        animation_ratio or 0,
    )

    if strongest < 0.30:
        return None

    score = clamp_score(35 + strongest * 70)
    return Finding(
        id="unstable-frame-pacing",
        title="Frame pacing instavel",
        hypothesis=(
            "A cadencia dos frames parece irregular o bastante para gerar stutter "
            "mesmo quando o FPS medio parece aceitavel."
        ),
        severity=severity(score),
        confidence="high" if between and between.count >= 10 else "medium",
        score=score,
        evidence=[
            Evidence(
                "MsBetweenPresents stdev/p50",
                fmt_ratio(between_jitter),
                "Variacao relativa no intervalo entre presents.",
            ),
            Evidence(
                "MsBetweenPresents p99/p50",
                fmt_ratio(p99_ratio),
                "Cauda longa de frames em relacao ao frame tipico.",
            ),
            Evidence(
                "DisplayedTime stdev/p50",
                fmt_ratio(displayed_jitter),
                "Variacao relativa do tempo exibido.",
            ),
            Evidence(
                "MsAnimationError p95",
                fmt_ms(animation_p95),
                "Erro de animacao p95 informado pelo PresentMon.",
            ),
        ],
        recommendation=(
            "Priorize estabilidade de frame time: investigue carregamento tardio, "
            "stalls de CPU/GPU, limite de FPS e composicao do display."
        ),
    )


def undisplayed_frames(frames: list[FrameSample]) -> Finding | None:
    if not any("DisplayedTime" in frame.raw for frame in frames):
        return None
    missing = [frame for frame in frames if frame.displayed_missing]
    if not missing:
        return None

    share = len(missing) / len(frames)
    score = clamp_score(40 + share * 80)
    return Finding(
        id="undisplayed-frames",
        title="Frames possivelmente desperdicados ou nao exibidos",
        hypothesis=(
            "Uma parte dos frames nao tem DisplayedTime, sugerindo frames "
            "descartados, substituidos ou nao efetivamente apresentados ao usuario."
        ),
        severity=severity(score),
        confidence=confidence_from_share(share),
        score=score,
        evidence=[
            Evidence(
                "Frames sem DisplayedTime",
                f"{len(missing)} / {len(frames)}",
                "Linhas onde DisplayedTime veio vazio, NA ou equivalente.",
            ),
            Evidence(
                "Participacao",
                fmt_percent(share),
                "Quanto trabalho pode nao ter chegado ao display.",
            ),
        ],
        recommendation=(
            "Investigue filas de present, frame generation, modo de janela/tela e "
            "se a aplicacao esta produzindo frames que sao substituidos antes do display."
        ),
    )


def composition_waste(
    frames: list[FrameSample], summary: TraceSummary, target_ms: float
) -> Finding | None:
    modes = [frame.present_mode for frame in frames if frame.present_mode]
    if not modes:
        return None

    composed = [mode for mode in modes if "composed" in mode.lower()]
    if not composed:
        return None

    share = len(composed) / len(modes)
    latency = summary.metrics.get("DisplayLatency")
    between = summary.metrics.get("MsBetweenPresents")
    latency_ratio = ratio(latency.p95 if latency else None, target_ms)
    jitter_ratio = ratio(between.stdev if between else None, between.p50 if between else None)

    if share < 0.25 or ((latency_ratio or 0) < 1.25 and (jitter_ratio or 0) < 0.25):
        return None

    score = clamp_score(32 + share * 25 + (latency_ratio or 0) * 14 + (jitter_ratio or 0) * 40)
    return Finding(
        id="composition-waste",
        title="Possivel desperdicio por composicao",
        hypothesis=(
            "A apresentacao passa por um modo composto enquanto latencia ou pacing "
            "ja parecem ruins, aumentando a chance de copia/composicao redundante."
        ),
        severity=severity(score),
        confidence="medium",
        score=score,
        evidence=[
            Evidence(
                "Frames compostos",
                f"{len(composed)} / {len(modes)}",
                "Frames cujo PresentMode contem Composed.",
            ),
            Evidence(
                "Participacao",
                fmt_percent(share),
                "Quanto do trace passou por modo composto.",
            ),
            Evidence(
                "DisplayLatency p95/frame",
                fmt_ratio(latency_ratio),
                "Relacao entre latencia de display p95 e tempo tipico de frame.",
            ),
            Evidence(
                "Pacing jitter",
                fmt_ratio(jitter_ratio),
                "Variacao relativa em MsBetweenPresents.",
            ),
        ],
        recommendation=(
            "Teste modo exclusive/fullscreen, flip model, overlays e composicao do "
            "DWM para separar custo inevitavel de transporte redundante."
        ),
    )


def most_common(values: list[str]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


def clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def severity(score: int) -> str:
    if score >= 85:
        return "critical"
    if score >= 70:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def confidence_from_share(share: float) -> str:
    if share >= 0.60:
        return "high"
    if share >= 0.20:
        return "medium"
    return "low"
