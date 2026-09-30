# 0003. Flat API keys

Status: accepted, 2026-09-30

## Context

The server controls the Docker socket, so anyone who can call it has root-level
power over the host. The first users are single teams running their own agents
on their own machine, not multi-tenant platforms.

## Decision

Authenticate with a list of static API keys from `AGENT_SANDBOX_API_KEYS`, sent
as `Authorization: Bearer <key>` or `X-API-Key: <key>`. Each key must be at least
16 characters, and the server compares keys in constant time. The server refuses
to start without a key unless you set `AGENT_SANDBOX_INSECURE_NO_AUTH=true`.
Every key can see and control every sandbox.

## Consequences

- Setup is one environment variable, and the MCP server and the SDK need only
  a URL and a key.
- There is no per-key isolation or quota. The roadmap lists multi-tenant keys,
  and the docs tell you to treat a key as a root credential until then.
- Rotating a key means restarting the server with a new list.
