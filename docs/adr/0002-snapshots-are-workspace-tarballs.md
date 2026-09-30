# 0002. Snapshots are workspace tarballs

Status: accepted, 2026-09-30

## Context

Agents need to undo a bad change and to branch from a known-good state. Options
included `docker commit` of the whole container, checkpoint and restore with
CRIU, filesystem-level snapshots (btrfs, ZFS, overlay layers), and a plain
archive of the directory the agent works in.

## Decision

A snapshot is a tar of `/workspace`, written by the backend's
`export_workspace` and stored by the manager in the server's data directory.
Rollback destroys the container, creates a fresh one with the same spec, and
extracts the tar into the new workspace. Fork does the same into a new sandbox
ID. Snapshots have their own records and outlive their source sandbox.
`AGENT_SANDBOX_MAX_SNAPSHOT_BYTES` caps the size.

## Consequences

- Snapshots work on every Docker storage driver and every backend that can
  stream a tar, with no host filesystem requirements.
- Rollback always starts from a clean root filesystem, which matches the
  read-only rootfs default.
- Memory, running processes, and `/tmp` don't survive a rollback. The docs say
  so, and a Firecracker backend could add full-VM snapshots as an optional
  capability.
- Large workspaces make snapshots slow and big, so the size cap matters.
