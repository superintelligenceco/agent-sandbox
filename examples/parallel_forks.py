"""Fork one snapshot into several sandboxes and try a different approach in each.

This is the pattern an agent uses to explore alternatives without them
stepping on each other: prepare once, snapshot, fork, compare, keep the winner.
"""

from concurrent.futures import ThreadPoolExecutor

from agent_sandbox.client import SandboxClient

CANDIDATES = {
    "loop": "def total(n):\n    s = 0\n    for i in range(n):\n        s += i\n    return s\n",
    "builtin": "def total(n):\n    return sum(range(n))\n",
    "formula": "def total(n):\n    return n * (n - 1) // 2\n",
}

BENCH = (
    'python3 -c "import timeit, solution; '
    "assert solution.total(10) == 45; "
    "print(round(min(timeit.repeat('solution.total(100000)', globals=globals(), number=20, repeat=3)), 4))\""
)


def main() -> None:
    with SandboxClient() as client, client.create(image="python:3.12-slim") as base:
        base.write_file("README", "shared setup lives here\n")
        snapshot = base.snapshot("prepared")

        def trial(name: str) -> tuple[str, str]:
            with client.fork(snapshot, timeout_seconds=300) as sandbox:
                sandbox.write_file("solution.py", CANDIDATES[name])
                result = sandbox.exec(BENCH)
                return name, result.stdout.strip() if result.ok else f"failed: {result.stderr.strip()}"

        with ThreadPoolExecutor(max_workers=len(CANDIDATES)) as pool:
            for name, seconds in pool.map(trial, CANDIDATES):
                print(f"{name:8} {seconds}")
        client.delete_snapshot(snapshot.id)


if __name__ == "__main__":
    main()
