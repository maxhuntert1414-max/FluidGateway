"""Read-only diagnosis of opt-in Runtime application-session evidence."""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

from .atomic_io import atomic_write_json, atomic_write_text

COUNTERS = (
    "instances", "devices", "allocations", "frees", "allocation_bytes", "live_bytes",
    "peak_bytes", "host_visible_bytes", "device_local_bytes", "maps", "flushes",
    "invalidates", "buffer_binds", "buffer_copies", "buffer_copy_bytes",
    "buffer_image_copies", "fills", "barriers", "submits", "presents", "api_errors",
    "untracked_allocations", "active_instances", "active_devices", "intercepted_calls",
    "unmaps", "image_binds", "queue_waits", "fence_waits", "copy2_calls",
    "submit2_calls", "telemetry_failures",
)
DECREASING_COUNTERS = {"live_bytes", "active_instances", "active_devices"}


def _number(value: object, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid application-session number: {name}")
    return value


def analyze_application_session(path: str | Path) -> dict:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig") as stream:
        text = stream.read(16 * 1024 * 1024 + 1)
    if len(text) > 16 * 1024 * 1024:
        raise ValueError("Application-session report exceeds 16 MiB.")
    report = json.loads(text)
    if not isinstance(report, dict) or report.get("schema") != "fluidruntime-application-session-v1":
        raise ValueError("Unsupported application-session schema.")
    for key in ("native_actuation_enabled", "performance_claim_allowed"):
        if report.get(key) is not False:
            raise ValueError("Observation evidence cannot authorize GPU actuation or performance claims.")
    for key in ("observation_requested", "layer_verified", "process_exited"):
        if type(report.get(key)) is not bool:
            raise ValueError(f"Invalid session flag: {key}")
    if type(report.get("process_id")) is not int or report["process_id"] <= 0:
        raise ValueError("Invalid process identity.")
    if not isinstance(report.get("executable"), str) or not report["executable"]:
        raise ValueError("Missing executable identity.")
    for key in ("executable_sha256", "layer_sha256"):
        value = report.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"Invalid binary hash: {key}")
    duration = _number(report.get("elapsed_milliseconds"), "elapsed_milliseconds")
    samples = report.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 1024:
        raise ValueError("Application session needs 1..1024 samples.")
    previous_time = -1.0
    previous = None
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError("Invalid application sample.")
        elapsed = _number(sample.get("elapsed_milliseconds"), "sample time")
        if elapsed < previous_time or elapsed > duration + 1:
            raise ValueError("Samples must be ordered and bounded by session duration.")
        previous_time = elapsed
        for key in ("cpu_milliseconds", "working_set_bytes", "private_bytes", "thread_count"):
            _number(sample.get(key), key)
        counters = sample.get("vulkan")
        if not isinstance(counters, dict) or set(counters) != set(COUNTERS):
            raise ValueError("Incomplete or unknown Vulkan counter schema.")
        for key, value in counters.items():
            if type(value) is not int or not 0 <= value <= 2**63 - 1:
                raise ValueError(f"Invalid Vulkan counter: {key}")
            if previous and key not in DECREASING_COUNTERS and value < previous[key]:
                raise ValueError(f"Vulkan cumulative counter moved backwards: {key}")
        previous = counters
    counters = samples[-1]["vulkan"]
    verified = report["layer_verified"]
    if verified and (not report["observation_requested"] or counters["devices"] == 0):
        raise ValueError("Layer verification contradicts native device evidence.")
    lease = report.get("windows_priority")
    if lease is not None:
        if (not verified or not isinstance(lease, dict) or type(lease.get("process_id")) is not int
                or lease.get("process_id") != report["process_id"]
                or lease.get("target_sha256") != report["executable_sha256"]
                or lease.get("before") != "Normal" or lease.get("requested") != "AboveNormal"
                or lease.get("authority") != "explicit-user-timed-priority-only"
                or type(lease.get("applied")) is not bool):
            raise ValueError("Windows priority evidence has an invalid identity or authority.")
        state = lease.get("restoration")
        if (state not in {"restored", "process-exited", "external-change-preserved", "not-applied",
                          "restore-not-confirmed", "restore-failed"}
                or type(lease.get("requested_seconds")) is not int or not 1 <= lease["requested_seconds"] <= 30
                or type(lease.get("start_time_utc_ticks")) is not int or lease["start_time_utc_ticks"] <= 0
                or (state == "restored" and (not lease["applied"] or lease.get("after") != "Normal"))):
            raise ValueError("Windows priority restoration evidence contradicts the lease contract.")
        _number(lease.get("elapsed_milliseconds"), "priority duration")
    findings = []

    def finding(code: str, title: str, evidence: dict, recommendation: str):
        findings.append({"id": code, "title": title, "evidence": evidence,
                         "recommendation": recommendation, "inferred": True})

    if report.get("failure") or not verified:
        finding("incomplete-session", "Sessao sem observacao Vulkan completa",
                {"samples": len(samples), "devices": counters["devices"]},
                "Confira a falha do Runtime e a API usada pelo executavel. Nao promover intervencao.")
    if counters["api_errors"]:
        finding("api-errors", "Chamadas Vulkan retornaram erros",
                {"negative_results": counters["api_errors"]},
                "Investigue com validacao Vulkan; o contador nao distingue device loss de erros recuperaveis.")
    if counters["untracked_allocations"]:
        finding("tracking-capacity", "Limite de rastreamento de alocacoes atingido",
                {"untracked_allocations": counters["untracked_allocations"]},
                "Trate bytes vivos e pico como cobertura parcial, nunca como VRAM fisica.")
    if counters["buffer_copy_bytes"]:
        finding("recorded-transfers", "Volume de copias de buffers registrado",
                {"recorded_copy_bytes": counters["buffer_copy_bytes"], "copy_calls": counters["buffer_copies"]},
                "Correlacione com uso real e reutilizacao de command buffers. Volume nao prova redundancia.")
    if counters["queue_waits"]:
        finding("queue-idle-waits", "Esperas por fila ociosa observadas",
                {"queue_wait_idle_calls": counters["queue_waits"], "submit_calls": counters["submits"]},
                "Separe inicializacao/encerramento de gameplay; nao remova sincronizacoes por contagem.")
    if lease and lease.get("restoration") not in ("restored", "process-exited", "external-change-preserved"):
        finding("priority-rollback", "Restauracao de prioridade nao confirmada",
                {"applied": int(lease["applied"])},
                "Inspecione a prioridade do PID e o relatorio do watchdog antes de repetir.")
    return {"schema": "fluidgateway-application-diagnosis-v1", "source": str(source),
            "process_id": report["process_id"], "executable": report["executable"],
            "duration_ms": duration, "sample_count": len(samples), "layer_verified": verified,
            "failure": report.get("failure"), "windows_priority": lease, "counters": counters,
            "working_set_peak_bytes": max(s["working_set_bytes"] for s in samples),
            "private_peak_bytes": max(s["private_bytes"] for s in samples), "findings": findings,
            "native_actuation_allowed": False, "performance_claim_allowed": False,
            "limitations": ["Diagnostico inferido, nao prova absoluta de causa interna.",
                            "Amostras atomicas independentes; cobertura de extensoes parcial.",
                            "Bytes registrados nao sao trafego fisico nem prova de copias executadas.",
                            "Contagens de apresentacao nao medem frames exibidos nem latencia de input.",
                            "O Gateway nao aplica prioridade automaticamente; o usuario autoriza uma lease limitada."]}


def write_application_report(report: dict, out: str | Path) -> tuple[Path, Path]:
    output = Path(out).with_suffix(".html")
    json_path = output.with_suffix(".json")
    if Path(report["source"]).resolve() in (output.resolve(), json_path.resolve()):
        raise ValueError("Diagnosis output must not overwrite the source application session.")
    rows = "".join(f"<tr><td>{html.escape(key)}</td><td>{value:,}</td></tr>"
                   for key, value in report["counters"].items())
    findings = "".join(f"<section><h2>{html.escape(item['title'])}</h2>"
                       f"<p>{html.escape(json.dumps(item['evidence']))}</p>"
                       f"<p>{html.escape(item['recommendation'])}</p></section>" for item in report["findings"])
    limits = "".join(f"<li>{html.escape(text)}</li>" for text in report["limitations"])
    body = f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FluidGateway | Aplicacao</title><style>
body{{font:16px/1.5 'Segoe UI',sans-serif;color:#20242b;background:#f6f7f9;margin:0}}
main{{max-width:1000px;margin:auto;padding:24px}}h1{{font-size:26px}}h2{{font-size:20px}}
section{{border-top:1px solid #bcc5cf;padding:12px 0}}table{{border-collapse:collapse;width:100%}}
td{{padding:6px;border-bottom:1px solid #ccd2d8;overflow-wrap:anywhere}}td:last-child{{text-align:right}}
p,li{{overflow-wrap:anywhere}}</style><main><h1>FluidGateway | Aplicacao</h1>
<p>{html.escape(report['executable'])} | PID {report['process_id']}</p>
<p>{report['sample_count']} amostras | {report['duration_ms']/1000:.2f} s |
Vulkan verificado: {report['layer_verified']}</p>
<p>Falha: {html.escape(str(report['failure'] or 'nenhuma registrada'))}</p>
<p>RAM: pico de working set {report['working_set_peak_bytes']/1048576:.2f} MiB;
memoria privada {report['private_peak_bytes']/1048576:.2f} MiB.</p>
<p>Prioridade Windows: {html.escape(json.dumps(report['windows_priority']))}</p>
{findings}<h2>Contadores Vulkan</h2><table>{rows}</table><h2>Limites</h2><ul>{limits}</ul></main></html>"""
    atomic_write_text(output, body)
    atomic_write_json(json_path, report)
    return output, json_path
