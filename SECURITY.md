# Security Policy

## Supported Development Line

FluidGateway is pre-1.0 research software. Security fixes target the latest
`main` branch unless a release note says otherwise.

## Reporting A Vulnerability

Please do not open a public issue for an undisclosed vulnerability.

Use GitHub's private vulnerability reporting or Security Advisory flow for this
repository when available. If that path is unavailable, contact the repository
owner through GitHub with only the minimum public detail needed to establish a
private channel.

Include:

- affected commit or version;
- operating system and Python version;
- reproduction steps or a minimal proof of concept;
- expected impact;
- whether the issue crosses a process, network, or privilege boundary.

## Project Boundary

The project does not authorize testing against software you do not own or have
explicit permission to inspect. Reports involving anti-cheat bypass, covert
injection, DRM circumvention, or unrelated third-party exploitation are outside
the intended scope.

## Local Trust Boundary

`runtime serve-events` binds only to IPv4 loopback. On Windows it requests
exclusive address ownership, bounds concurrent sessions, and applies absolute
read deadlines. It does not authenticate arbitrary local clients and must not
be exposed through a proxy or port forward. The server returns bounded
decisions but does not inject code or perform native actuation. FluidRuntime is
responsible for pinning the expected Gateway process identity and executable
hash before any owned-lab authorization is accepted.

Reports, ledgers, registries, and daemon state use same-directory temporary
files followed by atomic replacement. This protects the previous complete file
from interruption during a single write; it is not a transactional database or
a multi-host coordination mechanism.

Please allow maintainers time to reproduce and address a valid report before
public disclosure.
