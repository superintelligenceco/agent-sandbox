"""Compare a pytest-benchmark JSON report with the committed baseline.

Usage: python scripts/bench_compare.py benchmarks/baseline.json bench.json [--max-ratio 2.0]

The script compares the minimum time of each benchmark, which is the statistic
least sensitive to noisy neighbours on shared CI runners, and exits with status
1 when any benchmark is more than ``--max-ratio`` times slower than the baseline.
It prints a Markdown table, so CI can append it to the job summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load(path: Path) -> dict[str, float]:
    data = json.loads(path.read_text())
    return {bench["name"]: float(bench["stats"]["min"]) for bench in data["benchmarks"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--max-ratio", type=float, default=2.0)
    args = parser.parse_args(argv)

    baseline, current = load(args.baseline), load(args.current)
    failed = False
    print("| Benchmark | Baseline min (ms) | Current min (ms) | Ratio | |")
    print("| --- | ---: | ---: | ---: | --- |")
    for name in sorted(current):
        now = current[name]
        if name not in baseline:
            print(f"| `{name}` | n/a | {now * 1e3:.3f} | n/a | new |")
            continue
        ratio = now / baseline[name]
        verdict = "ok" if ratio <= args.max_ratio else f"REGRESSION (> {args.max_ratio:g}x)"
        failed |= ratio > args.max_ratio
        print(f"| `{name}` | {baseline[name] * 1e3:.3f} | {now * 1e3:.3f} | {ratio:.2f}x | {verdict} |")
    missing = sorted(set(baseline) - set(current))
    if missing:
        print(f"\nMissing from this run: {', '.join(missing)}")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
