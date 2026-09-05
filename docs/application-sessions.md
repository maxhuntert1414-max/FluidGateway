# Application-Session Reports

Current Gateway `main` imports `fluidruntime-application-session-v1` from
FluidRuntime v0.23. This command is not present in the older v0.67.1 release tag.

```powershell
python -m fluidgateway analyze-app `
  --session ..\FluidRuntime\artifacts\session.json --out tmp\application.html
```

Outputs are `application.html` and `application.json`. The CLI is read-only:
it does not launch, inject into or change priority of the source application.
Create sessions using Runtime's
[opt-in application guide](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/application-sessions.md).

The importer bounds input size/sample count, validates executable/layer hashes,
32 numeric counter fields, sample order, cumulative counters, observation flags
and any Windows priority lease. It rejects evidence that claims external GPU
actuation, performance gains, or contradictory successful priority restoration.
This is format validation, not cryptographic attestation of an untrusted report.

Findings include incomplete observation, negative Vulkan results, allocation
tracking overflow, recorded buffer-copy volume, queue-idle waits and unconfirmed
priority restoration. Every finding includes numeric evidence. They remain
hypotheses: counts do not establish redundant work, actual transferred bytes,
displayed FPS, input latency, or scheduling benefit.

Requested Vulkan allocation sizes are not physical residency. Host-visible and
device-local categories can overlap. CPU/RAM are sampled, not continuous;
counter snapshots are independently atomic rather than simultaneous. The
Runtime's experimental extension coverage and same-user trust limits still apply.
`native_actuation_allowed` and `performance_claim_allowed` always remain false.

Tests: `python -m unittest tests.test_application_session`, then `python -m unittest`.
Measured compatibility/rollback and negative performance-claim boundaries:
[v0.23 evidence](https://github.com/maxhuntert1414-max/FluidRuntime/blob/main/docs/evidence/v0.23.0-application-integration.md).
