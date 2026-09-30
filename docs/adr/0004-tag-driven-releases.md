# 0004. Tag-driven releases

Status: accepted, 2026-09-30

## Context

The project first used release-please, which opens a release pull request and
creates the tag when you merge it. The release also has to build a multi-arch
image, standalone executables on four runners, a wheel and an sdist, SBOMs, and
attestations, and publish to PyPI. Two release paths made it unclear which one
produced the files.

## Decision

Remove release-please. A pushed `v*` tag runs `release.yml`, which checks that the
tag matches `agent_sandbox.__version__`, builds and tests every artifact, signs
and attests the image, attaches the files and `SHA256SUMS` to the GitHub
Release, writes the release notes from the matching `CHANGELOG.md` entry, and
publishes `sic-agent-sandbox` to PyPI. A manual run builds the same files and
pushes the image as `edge` without publishing a release.

## Consequences

- One workflow owns every release artifact, and a manual run rehearses the whole
  release before you tag.
- You update `CHANGELOG.md` and `__version__` by hand before tagging.
- A bad tag fails fast at the version check instead of publishing mismatched
  files.
