from __future__ import annotations

import html
from pathlib import Path

from .atomic_io import atomic_write_json, atomic_write_text
from .models import AnalysisReport, Finding, ManagementAction, ManagementPlan, MetricSummary
from .stats import fmt_ms


def write_report(report: AnalysisReport, html_path: str | Path) -> tuple[Path, Path]:
    output_path = Path(html_path)
    if output_path.suffix.lower() != ".html":
        output_path = output_path.with_suffix(".html")
    json_path = output_path.with_suffix(".json")

    atomic_write_text(output_path, render_html(report))
    atomic_write_json(json_path, report.to_dict())
    return output_path, json_path


def write_management_plan(plan: ManagementPlan, json_path: str | Path) -> Path:
    output_path = Path(json_path)
    if output_path.suffix.lower() != ".json":
        output_path = output_path.with_suffix(".json")
    atomic_write_json(output_path, plan.to_dict())
    return output_path


def render_html(report: AnalysisReport) -> str:
    summary = report.summary
    findings = report.findings
    modes = ", ".join(summary.present_modes) if summary.present_modes else "n/a"
    runtimes = ", ".join(summary.runtimes) if summary.runtimes else "n/a"
    fps = "n/a" if summary.approx_fps is None else f"{summary.approx_fps:.1f}"
    duration = fmt_ms(summary.duration_ms)

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FluidGateway Report</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #18202a;
      --muted: #5a6675;
      --line: #d8dee8;
      --accent: #0b6bcb;
      --critical: #b42318;
      --high: #c2410c;
      --medium: #9a6700;
      --low: #326b40;
    }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
      line-height: 1.45;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      padding-bottom: 20px;
      margin-bottom: 22px;
    }}
    h1, h2, h3 {{
      margin: 0;
      line-height: 1.2;
    }}
    h1 {{
      font-size: 32px;
    }}
    h2 {{
      font-size: 22px;
      margin-top: 28px;
      margin-bottom: 12px;
    }}
    h3 {{
      font-size: 18px;
      margin-bottom: 8px;
    }}
    .subtitle {{
      color: var(--muted);
      margin-top: 8px;
      max-width: 820px;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 10px;
      margin-top: 18px;
    }}
    .stat, .finding, .notice {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .stat {{
      padding: 12px;
    }}
    .stat span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    .stat strong {{
      display: block;
      margin-top: 6px;
      font-size: 18px;
    }}
    .notice {{
      padding: 14px 16px;
      color: var(--muted);
    }}
    .finding {{
      padding: 18px;
      margin-bottom: 12px;
    }}
    .finding-top {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px 12px;
      justify-content: space-between;
      align-items: start;
    }}
    .badges {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .badge {{
      border-radius: 999px;
      padding: 4px 9px;
      border: 1px solid var(--line);
      font-size: 12px;
      font-weight: 700;
      background: #f9fafb;
    }}
    .critical {{ color: var(--critical); }}
    .high {{ color: var(--high); }}
    .medium {{ color: var(--medium); }}
    .low {{ color: var(--low); }}
    .evidence {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 8px;
      margin-top: 12px;
    }}
    .evidence-item {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbfcfe;
    }}
    .evidence-item span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
    }}
    .evidence-item strong {{
      display: block;
      margin: 3px 0;
      font-size: 16px;
    }}
    .recommendation {{
      margin-top: 12px;
      color: var(--muted);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    th, td {{
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
    }}
    th:first-child, td:first-child {{
      text-align: left;
    }}
    th {{
      background: #eef2f7;
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    tr:last-child td {{
      border-bottom: 0;
    }}
    .small {{
      color: var(--muted);
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>FluidGateway Report</h1>
      <p class="subtitle">{escape(report.disclaimer)}</p>
      <div class="summary-grid">
        <div class="stat"><span>Aplicacao</span><strong>{escape(summary.application)}</strong></div>
        <div class="stat"><span>Runtime</span><strong>{escape(runtimes)}</strong></div>
        <div class="stat"><span>Frames</span><strong>{summary.frame_count}</strong></div>
        <div class="stat"><span>Duracao</span><strong>{duration}</strong></div>
        <div class="stat"><span>FPS aprox.</span><strong>{fps}</strong></div>
      </div>
    </header>

    <section>
      <h2>Top desperdicios</h2>
      {render_findings(findings)}
    </section>

    <section>
      <h2>Management inteligente</h2>
      {render_management_plan(report.management_plan)}
    </section>

    <section>
      <h2>Resumo de metricas</h2>
      {render_metrics_table(report)}
    </section>

    <section>
      <h2>Contexto</h2>
      <div class="notice">
        <p><strong>Present modes:</strong> {escape(modes)}</p>
        <p><strong>Colunas ausentes:</strong> {escape(", ".join(summary.missing_columns) if summary.missing_columns else "nenhuma")}</p>
        <p class="small">FluidGateway v0 mede sinais e gera hipoteses. A meta de longo prazo e evoluir esse mapa de desperdicio para orientar um gateway/scheduler inteligente de processamento.</p>
      </div>
    </section>
  </main>
</body>
</html>
"""


def render_findings(findings: list[Finding]) -> str:
    if not findings:
        return (
            '<div class="notice">Nenhum desperdicio forte foi detectado com as '
            "heuristicas atuais. Isso nao prova ausencia de problema; so indica "
            "que o trace nao cruzou os limiares do v0.</div>"
        )

    return "\n".join(render_finding(finding) for finding in findings)


def render_finding(finding: Finding) -> str:
    evidence = "\n".join(
        f"""<div class="evidence-item">
          <span>{escape(item.label)}</span>
          <strong>{escape(item.value)}</strong>
          <span>{escape(item.detail)}</span>
        </div>"""
        for item in finding.evidence
    )
    return f"""<article class="finding">
      <div class="finding-top">
        <div>
          <h3>{escape(finding.title)}</h3>
          <p>{escape(finding.hypothesis)}</p>
        </div>
        <div class="badges">
          <span class="badge {escape(finding.severity)}">score {finding.score}</span>
          <span class="badge">severity {escape(finding.severity)}</span>
          <span class="badge">confidence {escape(finding.confidence)}</span>
        </div>
      </div>
      <div class="evidence">{evidence}</div>
      <p class="recommendation"><strong>Recomendacao:</strong> {escape(finding.recommendation)}</p>
    </article>"""


def render_management_plan(plan: ManagementPlan) -> str:
    if not plan.actions:
        return f"""<div class="notice">
        <p>{escape(plan.summary)}</p>
        <p class="small">{escape('; '.join(plan.constraints))}</p>
      </div>"""

    actions = "\n".join(render_management_action(action) for action in plan.actions)
    constraints = "".join(
        f"<li>{escape(constraint)}</li>" for constraint in plan.constraints
    )
    return f"""<div class="notice">
        <p><strong>Modo:</strong> {escape(plan.mode)}</p>
        <p>{escape(plan.summary)}</p>
        <p class="small">Estas politicas sao advisory: descrevem como o futuro gateway/scheduler deve agir, sem alterar jogo, driver ou sistema nesta versao.</p>
      </div>
      {actions}
      <div class="notice">
        <p><strong>Restricoes v0.2</strong></p>
        <ul>{constraints}</ul>
      </div>"""


def render_management_action(action: ManagementAction) -> str:
    evidence = "\n".join(
        f"""<div class="evidence-item">
          <span>{escape(item.label)}</span>
          <strong>{escape(item.value)}</strong>
          <span>{escape(item.detail)}</span>
        </div>"""
        for item in action.evidence
    )
    return f"""<article class="finding">
      <div class="finding-top">
        <div>
          <h3>{escape(action.title)}</h3>
          <p>{escape(action.objective)}</p>
        </div>
        <div class="badges">
          <span class="badge">priority {action.priority}</span>
          <span class="badge">confidence {escape(action.confidence)}</span>
          <span class="badge">{escape(action.layer)}</span>
        </div>
      </div>
      <p><strong>Policy:</strong> {escape(action.policy)}</p>
      <p><strong>Trigger:</strong> {escape(action.trigger)}</p>
      <p><strong>Expected effect:</strong> {escape(action.expected_effect)}</p>
      <p class="recommendation"><strong>Risk:</strong> {escape(action.risk)}</p>
      <div class="evidence">{evidence}</div>
    </article>"""


def render_metrics_table(report: AnalysisReport) -> str:
    rows = []
    for name, metric in report.summary.metrics.items():
        if metric.count == 0:
            continue
        rows.append(render_metric_row(name, metric))
    if not rows:
        return '<div class="notice">Nenhuma metrica numerica disponivel.</div>'
    return f"""<table>
      <thead>
        <tr>
          <th>Metrica</th>
          <th>Count</th>
          <th>Media</th>
          <th>p50</th>
          <th>p95</th>
          <th>p99</th>
          <th>Max</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>"""


def render_metric_row(name: str, metric: MetricSummary) -> str:
    return f"""<tr>
      <td>{escape(name)}</td>
      <td>{metric.count}</td>
      <td>{fmt_ms(metric.average)}</td>
      <td>{fmt_ms(metric.p50)}</td>
      <td>{fmt_ms(metric.p95)}</td>
      <td>{fmt_ms(metric.p99)}</td>
      <td>{fmt_ms(metric.maximum)}</td>
    </tr>"""


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)
