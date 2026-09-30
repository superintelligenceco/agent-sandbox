# Concepts

## Sandbox

A sandbox is an isolated environment with a writable `/workspace` directory. The
Docker backend runs each sandbox as one container plus one named volume mounted
at `/workspace`. A sandbox has an ID such as `sb_2f10f5a9403f25d0`, an image, CPU,
memory, and process-count limits, an optional network, and a time to live.

## Exec

`POST /v1/sandboxes/{id}/exec` runs a shell command to completion and returns
stdout, stderr, the exit code, and whether the command timed out.
`POST /v1/sandboxes/{id}/exec/stream` runs the same command and streams NDJSON
events (`stdout`, `stderr`, then one `exit`) as the output arrives. A timeout
kills the command's whole process group, not only the shell.

## Files

You read, write, and list files through the API. Uploads and downloads are raw
bytes, so binary files work. Writes must land inside `/workspace`, and the
manager validates every path before a backend sees it.

## Snapshot

A snapshot is a tar of `/workspace`, stored in the server's data directory. It
has an ID such as `snap_485f667dcf5910ac` and an optional name. Snapshots outlive
the sandbox they came from, so you can delete a sandbox and still fork its
snapshots later.

## Rollback

Rollback destroys the sandbox's container, creates a fresh one with the same
spec and the same ID, and extracts the snapshot into the new workspace. Anything
outside `/workspace`, such as running processes and `/tmp`, resets.

## Fork

Fork starts a new sandbox from a snapshot. Fork one snapshot several times to try
different approaches in parallel from the same known-good state.

## Time to live

Every sandbox has a TTL (`timeout_seconds`, 900 seconds by default). A reaper
destroys sandboxes whose TTL passed. `POST /v1/sandboxes/{id}/timeout` resets the
TTL, counted from now.

## Restart reconciliation

The manager persists a record for each sandbox in the data directory. When the
server restarts, it picks up its live sandboxes and removes containers and
volumes that carry the `io.agent-sandbox.managed=true` label but have no record.

## Security model

Read this section before you expose the server to anything you don't trust.

### What a sandbox gets by default

Each sandbox is one Docker container plus one named volume mounted at
`/workspace`. The container runs with:

- A non-root user (`1000:1000`), and `HOME=/workspace`.
- Every Linux capability dropped and `no-new-privileges` set.
- A read-only root filesystem. Only `/workspace` (a volume) and `/tmp` (a
  size-limited `nosuid,nodev` tmpfs) are writable.
- No network interface except loopback. When you request `network: true`, the
  sandbox joins a dedicated bridge network with inter-container traffic disabled.
- Memory, CPU, and process-count limits, with swap disabled.
- A private IPC namespace and an init process that reaps zombies.
- A fixed hostname and no host mounts other than its own volume.

The integration tests check each of these properties against a real Docker
daemon on every CI run.

### Honest limits

- **Containers are not virtual machines.** Every sandbox shares the host kernel.
  A kernel vulnerability can let code escape the container. If you run code from
  untrusted users, not only from your own agents, use a stronger runtime such as
  gVisor, or put the whole host inside a VM you're willing to lose.
- **The server controls Docker.** It needs the Docker socket, and access to the
  Docker socket is equivalent to root on the host. Treat the API key as a root
  credential, keep the port on localhost or behind TLS, and consider a Docker
  socket proxy that allows only the container, volume, image, network, and exec
  endpoints.
- **Network access is coarse.** `network: true` means outbound access to
  wherever the host can reach, which can include your LAN and cloud metadata
  endpoints. There's no egress allowlist yet. Leave networking off unless the
  task needs it, or block those ranges on the host.
- **Snapshots cover `/workspace` only.** Snapshots don't capture memory, running
  processes, `/tmp`, or changes to the root filesystem when you turn off
  `read_only_rootfs`. Rollback replaces the container, so all of that resets.
- **Limits aren't complete.** Disk use inside `/workspace` has no quota on most
  Docker storage drivers, and snapshot size has a server-side cap
  (`AGENT_SANDBOX_MAX_SNAPSHOT_BYTES`) but no per-key budget.
- **API keys are flat.** Every key can see and control every sandbox. There are
  no per-key namespaces yet.

Report vulnerabilities as described in [SECURITY.md](https://github.com/superintelligenceco/agent-sandbox/blob/main/SECURITY.md).
