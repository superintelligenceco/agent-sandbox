# Backends

A backend turns the manager's calls into operations on one isolation
technology. The manager owns IDs, quotas, TTLs, locking, path validation, and
snapshot storage, so a backend stays small.

## The contract

Every backend subclasses `agent_sandbox.backends.base.Backend` and keeps these
rules:

| Method | Contract |
| --- | --- |
| `ping()` | Raise `BackendError` when the runtime is unreachable. |
| `create(id, spec)` | Start an isolated environment with an empty, writable `/workspace` owned by the sandbox user. Apply every limit in `SandboxSpec`. On failure, leave nothing behind. |
| `destroy(id)` | Remove the environment and its storage. Calling it twice, or for an unknown ID, must succeed. |
| `list_ids()` | Return every sandbox ID the backend still holds resources for, including stopped ones. The manager uses this list to remove orphans. |
| `is_running(id)` | Return `False` for unknown IDs instead of raising. |
| `exec(id, argv, env, workdir, timeout_seconds)` | Yield `ExecOutput` chunks as they arrive, then exactly one `ExecExit`. On timeout, kill every process the command started and set `timed_out`. |
| `read_file(id, path, max_bytes)` | Follow symlinks. Raise `NotFoundError`, `InvalidRequestError` for directories, and `PayloadTooLargeError` above `max_bytes`. |
| `write_file(id, path, data, mode)` | Create parent directories. Files belong to the sandbox user. |
| `list_files(id, path)` | Return direct children, including dotfiles. |
| `export_workspace(id, dest, max_bytes)` | Write `/workspace` as a tar stream with paths relative to `/workspace`, keeping modes. Stop with `PayloadTooLargeError` above `max_bytes`. |
| `import_workspace(id, src)` | Extract a tar stream from `export_workspace` into an empty workspace. |

The manager only calls `import_workspace` on a freshly created sandbox, so a
backend doesn't have to merge with existing files.

## Docker

`DockerBackend` is the backend that ships today. It runs each sandbox as one
long-lived container with a keep-alive process, and mounts a named volume at
`/workspace`. A short-lived helper container that holds only `CAP_CHOWN` hands
the new volume to the sandbox user, so the sandbox itself never holds a
capability. `exec` records the wrapper shell's PID in `/tmp` so a timeout can
kill the whole process group.

Everything the backend creates carries the label `io.agent-sandbox.managed=true`.

## Roadmap backends

These backends don't exist yet. The notes describe the intended design so that
contributors can pick them up.

### gVisor

gVisor's `runsc` is an OCI runtime, so the Docker backend can already pass it
through with `AGENT_SANDBOX_DOCKER_RUNTIME=runsc`. The project doesn't test that
configuration. Supporting it means a CI job that installs `runsc` and runs the
integration suite with it, plus fixes for any behavior that differs, such as the
`/proc` details the tests read.

### Firecracker

A Firecracker backend would boot a microVM per sandbox from a root filesystem
image built from the requested OCI image, with the workspace on a separate block
device and a small in-VM agent for exec and file calls over vsock. Firecracker
snapshots cover memory and CPU state, which would let rollback restore running
processes too. That requires a new, optional capability in the interface rather
than a change to `export_workspace`.
