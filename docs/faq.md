# FAQ

## Is a sandbox safe for untrusted code?

It's safe enough for code your own agents write, with the defaults on. Every
sandbox still shares the host kernel, so a kernel vulnerability can let code
escape. For code from untrusted users, run the host inside a VM you're willing to
lose, or use a stronger runtime. Read the
[security model](concepts.md#security-model) before you expose the server.

## Why does the server need the Docker socket?

The server creates, execs into, and removes containers through the Docker Engine
API. Access to the socket is equivalent to root on the host, so treat every API
key as a root credential and keep the port on localhost or behind TLS.

## Does a snapshot capture running processes or memory?

No. A snapshot is a tar of `/workspace`. Rollback starts a fresh container, so
processes, `/tmp`, and anything outside `/workspace` reset. The
[Firecracker backend on the roadmap](backends.md#firecracker) would capture
memory too.

## Can sandboxes reach the internet?

Not by default. A sandbox gets only a loopback interface unless you create it
with `"network": true`. Set `AGENT_SANDBOX_ALLOW_NETWORK=false` to refuse those
requests entirely.

## Which images can a sandbox use?

Any OCI image the Docker host can pull, as long as it has `/bin/sh`. Restrict the
list with `AGENT_SANDBOX_ALLOWED_IMAGES`, for example `python:*,node:22*`.

## Does it run on macOS or Windows?

The server is tested on Linux only. CI checks that the macOS and Windows
executables start and render the OpenAPI document, but it doesn't run sandboxes
on those systems. The Python SDK and the MCP server run
anywhere Python runs.

## Why is the PyPI package called `sic-agent-sandbox`?

The name `agent-sandbox` was taken on PyPI. The distribution is
`sic-agent-sandbox`, while the import package (`agent_sandbox`) and the commands
(`agent-sandbox`, `agent-sandbox-mcp`) keep their names.

## What happens when the server restarts?

The server reads its sandbox records from the data directory, keeps the
sandboxes that still run, and removes labeled containers and volumes that have no
record. Snapshots stay in the data directory.

## How do I verify a release?

Each release file has a build provenance attestation, and the image is signed
with cosign keyless signing:

```sh
gh attestation verify agent-sandbox-linux-x86_64 -R superintelligenceco/agent-sandbox
gh attestation verify oci://ghcr.io/superintelligenceco/agent-sandbox:v0.2.1 -R superintelligenceco/agent-sandbox
```
