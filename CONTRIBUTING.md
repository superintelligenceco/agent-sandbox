# Contributing to agent-sandbox

Thanks for your interest. This guide shows you how to set up a development
environment, run the checks that CI runs, and open a pull request.

## Before you start

- For a bug, open an issue with the bug report form first, unless the fix is
  small and obvious.
- For a new feature or an API change, open a feature request and agree on the
  shape before you write code. API changes are hard to undo.
- For a security problem, don't open an issue. Follow [SECURITY.md](SECURITY.md).

## Set up

You need Python 3.11 or later and a Docker daemon you can reach without `sudo`.

```sh
git clone https://github.com/superintelligenceco/agent-sandbox && cd agent-sandbox
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Run the checks

CI runs the same commands. Run them before you push:

```sh
ruff check .
ruff format --check .
mypy
pytest tests/unit
pytest tests/integration
```

The integration tests create real containers labeled
`io.agent-sandbox.managed=true`, and remove them when the session ends. They use
`alpine:3.20` unless you set `AGENT_SANDBOX_TEST_IMAGE`.

If you change the API, regenerate the spec and commit it:

```sh
agent-sandbox openapi -o docs/openapi.json
```

## Write good changes

- Keep pull requests small and focused on one change.
- Add tests. Unit tests use the in-memory backend in `tests/fakes.py`. Anything
  that touches isolation needs an integration test against real Docker.
- Keep the hardened defaults. A change that weakens isolation needs a strong
  reason, a README update in the security model section, and a maintainer's
  explicit agreement.
- Match the existing style. `ruff format` settles formatting, and `mypy --strict`
  must pass.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/). They keep the
history readable and make the changelog easy to write.

```text
feat(api): add a route to extend every sandbox of a key
fix(docker): kill the process group when an exec times out
docs: explain the snapshot size limit
```

## Cut a release

Releases come from tags. The `Release` workflow (`.github/workflows/release.yml`)
runs when you push a `v*` tag. It builds the wheel and sdist, pushes the
`linux/amd64` and `linux/arm64` image to GHCR as `vX.Y.Z` and `latest`,
smoke-tests the pushed image with the Compose file, and then creates the GitHub
Release for the tag (if it doesn't exist) and attaches the wheel, sdist,
`docker-compose.yml` pinned to `vX.Y.Z`, and `SHA256SUMS`.

1. Set `__version__` in `src/agent_sandbox/__init__.py` to the new version. The
   workflow fails if the tag and the version differ.
2. Move the `Unreleased` entries in `CHANGELOG.md` under the new version.
3. Commit, then tag and push:

   ```sh
   git tag -a v0.2.0 -m v0.2.0
   git push origin v0.2.0
   ```

To test the pipeline without a release, run it by hand with
`gh workflow run release.yml --ref main`. A manual run pushes the image as
`edge` and keeps the files as run artifacts.

The project doesn't use release-please: with the default `GITHUB_TOKEN`, it can't
open pull requests in this organization, and releases it creates don't trigger
other workflows.

## Add a backend

A backend implements `agent_sandbox.backends.base.Backend`. Read
[docs/backends.md](docs/backends.md) for the contract each method must keep,
then run the integration suite against your backend.

## Code of conduct

Everyone who takes part in this project agrees to the
[code of conduct](CODE_OF_CONDUCT.md).
