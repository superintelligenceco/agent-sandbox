## Summary

<!-- What does this change do, and why? Link the issue it resolves. -->

## Testing

<!-- How did you verify the change? Paste the commands you ran. -->

## Checklist

- [ ] `ruff check .`, `ruff format --check .`, and `mypy` pass.
- [ ] `pytest` passes, including `tests/integration` against a real Docker daemon.
- [ ] New behavior has tests.
- [ ] If the API changed, `docs/openapi.json` is regenerated and the README is updated.
- [ ] If the change touches isolation defaults, the security model in the README is updated.
- [ ] The PR title follows [Conventional Commits](https://www.conventionalcommits.org/).
