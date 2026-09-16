from __future__ import annotations

import os
from typing import Any


def _iter_current_benchmarks(benchmarksession: Any):
    for _, benchmarks in benchmarksession.groups or []:
        for bench in benchmarks:
            if bench.get("path") is None or bench.get("source") == "NOW":
                yield bench


def _find_baseline_mean(benchmarksession: Any, fullname: str) -> float | None:
    for compared_mapping in (benchmarksession.compared_mapping or {}).values():
        compared = compared_mapping.get(fullname)
        if compared:
            return compared["stats"]["mean"]
    return None


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if os.environ.get("MINIMAL_MAGIC_DISABLE_BENCHMARK_SUMMARY") == "1":
        return

    benchmarksession = getattr(config, "_benchmarksession", None)
    if benchmarksession is None or not benchmarksession.groups:
        return

    rows = list(_iter_current_benchmarks(benchmarksession))
    if not rows:
        return

    for row in rows:
        row["name"] = benchmarksession.name_format(row)

    name_width = max(len("Name"), max(len(row["name"]) for row in rows))
    mean_width = max(len("Mean (ms)"), max(len(f"{row['mean'] * 1000:.4f}") for row in rows))
    ratio_width = max(len("x vs base"), max(len("1.00x") for row in rows))
    stddev_width = max(len("StdDev (ms)"), max(len(f"{row['stddev'] * 1000:.4f}") for row in rows))

    terminalreporter.write_line("")
    title = f" benchmark summary: {len(rows)} tests "
    terminalreporter.write_line(title.center(name_width + mean_width + ratio_width + stddev_width + 9, "-"), yellow=True)

    header = (
        f"{'Name'.ljust(name_width)}  "
        f"{'Mean (ms)'.rjust(mean_width)}  "
        f"{'x vs base'.rjust(ratio_width)}  "
        f"{'StdDev (ms)'.rjust(stddev_width)}"
    )
    terminalreporter.write_line(header)
    terminalreporter.write_line("-" * len(header), yellow=True)

    for row in rows:
        mean_ms = row["mean"] * 1000
        stddev_ms = row["stddev"] * 1000
        baseline_mean = _find_baseline_mean(benchmarksession, row["fullname"])
        ratio = f"{mean_ms / (baseline_mean * 1000):.2f}x" if baseline_mean else "-"
        terminalreporter.write_line(
            f"{row['name'].ljust(name_width)}  "
            f"{mean_ms:>{mean_width}.4f}  "
            f"{ratio:>{ratio_width}}  "
            f"{stddev_ms:>{stddev_width}.4f}"
        )

    terminalreporter.write_line("-" * len(header), yellow=True)
