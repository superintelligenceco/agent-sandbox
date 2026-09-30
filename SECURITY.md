# Security policy

agent-sandbox exists to contain untrusted code, so isolation bugs are the most
important bugs in this project.

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

## Report a vulnerability

Don't open a public issue. Report the problem privately through
[GitHub security advisories](https://github.com/superintelligenceco/agent-sandbox/security/advisories/new).

Include:

- What an attacker can do, and from where (inside a sandbox, with an API key, or
  without one).
- Steps to reproduce, ideally a request sequence or a command to run in a
  sandbox.
- The agent-sandbox version, Docker version, and host OS.

You get an acknowledgement within five working days. After the maintainers
confirm the problem, they agree a disclosure date with you and credit you in the
advisory unless you prefer otherwise.

## Scope

In scope:

- Code in a sandbox that reads or changes anything outside its own container and
  workspace volume, or that gains privileges inside the container.
- Bypasses of the documented defaults: non-root user, dropped capabilities,
  `no-new-privileges`, read-only root filesystem, network off, and resource
  limits.
- Requests that succeed without a valid API key, or path handling that lets a
  request write outside `/workspace`.
- Snapshot handling that lets one sandbox read or change another sandbox's data.

Out of scope, because the README documents these as limits:

- Container escapes that rely on an unpatched host kernel or Docker daemon.
  Report those upstream.
- Anything that a holder of a valid API key can already do through the API.
- Network access from sandboxes created with `network: true`.
