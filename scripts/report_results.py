#!/usr/bin/env python3
"""Validate measured benchmark records and write a compact Markdown report."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INPUTS = ("gradient_64", "gradient_128", "shapes_64", "shapes_128")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def positive_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def read_measurements(path: Path) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    config = data["configuration"]
    for field, expected in {
        "cores": 2, "threads_per_block": 4, "data_channels": 4,
        "program_channels": 1, "memory_response_cycles": 1,
        "tile_pixels": 128, "clock_period_ns": 10,
    }.items():
        require(config.get(field) == expected, f"Unexpected configuration: {field}")
    for field in ("python", "cocotb", "host"):
        require(isinstance(config.get(field), str) and bool(config[field]),
                f"Missing environment metadata: {field}")
    rows = data["results"]
    require(isinstance(rows, list) and len(rows) == len(EXPECTED_INPUTS),
            "Expected exactly four completed benchmark records")
    require(all(isinstance(row, dict) for row in rows), "Invalid benchmark record")
    by_name = {row.get("input"): row for row in rows}
    require(set(by_name) == set(EXPECTED_INPUTS), "Missing, duplicated, or unknown input")
    ordered = []
    for name in EXPECTED_INPUTS:
        row = by_name[name]
        size = int(name.rsplit("_", 1)[1])
        pixels = size * size
        launches = pixels // config["tile_pixels"]
        require(row.get("correct") is True, f"Correctness did not pass: {name}")
        for field, expected in {
            "width": size, "height": size, "pixels": pixels, "k": 50,
            "launches": launches, "launched_threads": pixels,
            "setup_cycles": 5 * launches, "clock_period_ns": 10,
        }.items():
            require(type(row.get(field)) is int and row[field] == expected,
                    f"Invalid {field}: {name}")
        require(type(row.get("kernel_cycles")) is int and row["kernel_cycles"] > 0,
                f"Invalid kernel cycle measurement: {name}")
        for field, expected in {
            "kernel_time_us": row["kernel_cycles"] * config["clock_period_ns"] / 1000,
            "cycles_per_pixel": row["kernel_cycles"] / pixels,
        }.items():
            require(positive_number(row.get(field))
                    and math.isclose(row[field], expected, rel_tol=1e-12, abs_tol=1e-12),
                    f"Inconsistent {field}: {name}")
        require(positive_number(row.get("simulator_wall_seconds")),
                f"Invalid simulator wall time: {name}")
        for image in (ROOT / "inputs" / f"{name}.png", path.parent / f"{name}_k50.png"):
            require(image.is_file() and image.stat().st_size > 0, f"Missing image: {image}")
        ordered.append(row)
    return config, ordered


def link(path: Path, report: Path) -> str:
    return Path(os.path.relpath(path, report.parent)).as_posix()


def render(config: dict, rows: list[dict], source: Path, report: Path) -> str:
    lines = [
        "# Tiny-GPU brightness benchmark", "",
        "Operation: `output = min(255, input + 50)` on unsigned 8-bit grayscale pixels. "
        "All four measured runs passed exact pixel comparisons, memory guards, and "
        "read/write transaction checks in the RTL testbench.", "",
        f"Source: [{source.name}]({link(source, report)}). "
        "This report is generated from completed measurements; it contains no estimated benchmark rows.", "",
        "| Input | Pixels | Launches | Kernel cycles | Simulated kernel time (µs) | Simulator wall time (s) | Correct |",
        "| --- | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['input']}.png | {row['pixels']:,} | {row['launches']:,} | "
            f"{row['kernel_cycles']:,} | {row['kernel_time_us']:,.3f} | "
            f"{row['simulator_wall_seconds']:.6f} | Yes |"
        )
    lines.extend([
        "", "## Timing and configuration", "",
        "Kernel cycles count rising edges from `start` through observed `done`, summed "
        "across launches. They exclude reset/configuration setup and host memory transfers. "
        "Setup is **5 cycles per launch**, reported separately below.", "",
        "The **10 ns simulation clock is arbitrary**: simulated kernel time equals "
        "`kernel cycles × 10 ns`. The equivalent 100 MHz is an assumption, not a measured "
        "or claimed achievable chip frequency.", "",
        "Simulator wall time measures the driver and RTL execution, including tile preparation, "
        "memory service, setup, and correctness checks. It excludes image loading/saving, "
        "compilation, and simulator startup. It varies with the host and is not hardware execution "
        "time. These measurements do not establish a CPU/GPU speedup.", "",
        "| Input | Setup cycles (excluded from kernel) | Kernel + setup cycles | Kernel cycles / pixel |",
        "| --- | ---: | ---: | ---: |",
    ])
    for row in rows:
        lines.append(
            f"| {row['input']}.png | {row['setup_cycles']:,} | "
            f"{row['kernel_cycles'] + row['setup_cycles']:,} | {row['cycles_per_pixel']:.4f} |"
        )
    lines.extend([
        "",
        f"Configuration: {config['cores']} cores, {config['threads_per_block']} threads per block, "
        f"{config['tile_pixels']} pixels per tile, {config['data_channels']} data-memory channels, "
        f"{config['program_channels']} program-memory channel, and memory responses after "
        f"{config['memory_response_cycles']} clock cycle. "
        "The two cores can execute up to eight pixel threads concurrently; larger images use repeated launches.",
        "", f"Recorded environment: Python {config['python']}; cocotb {config['cocotb']}; {config['host']}.",
        "", "## Scaling from 64 × 64 to 128 × 128", "",
    ])
    by_name = {row["input"]: row for row in rows}
    for pattern in ("gradient", "shapes"):
        small, large = by_name[f"{pattern}_64"], by_name[f"{pattern}_128"]
        pixel_ratio = large["pixels"] / small["pixels"]
        launch_ratio = large["launches"] / small["launches"]
        cycle_ratio = large["kernel_cycles"] / small["kernel_cycles"]
        wall_ratio = large["simulator_wall_seconds"] / small["simulator_wall_seconds"]
        lines.append(
            f"- **{pattern.capitalize()}:** {pixel_ratio:.2f}× as many pixels, "
            f"{launch_ratio:.2f}× as many launches, {cycle_ratio:.4f}× as many kernel cycles, "
            f"and {wall_ratio:.4f}× simulator wall time."
        )
    lines.extend([
        "", "The fourfold pixel increase requires four times as many complete 128-pixel tiles. "
        "Cycle ratios measure the resulting RTL work; wall-time ratios also reflect host execution "
        "and verification overhead. This is a size-scaling comparison within the same configuration.",
        "", "## Before and after", "",
        "Original synthetic grayscale inputs and their saved RTL outputs; every output uses `k = 50`.", "",
        "| Input | Before | After |", "| --- | --- | --- |",
    ])
    for row in rows:
        name = row["input"]
        before = link(ROOT / "inputs" / f"{name}.png", report)
        after = link(source.parent / f"{name}_k50.png", report)
        lines.append(f"| {name} | ![{name} original]({before}) | ![{name} brightness +50]({after}) |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "results" / "benchmark.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "REPORT.md")
    args = parser.parse_args()
    try:
        source, report = args.input.resolve(), args.output.resolve()
        config, rows = read_measurements(source)
        content = render(config, rows, source, report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(content, encoding="utf-8")
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(1, f"Cannot generate report: {error}\n")
    print(f"Created {report}")


if __name__ == "__main__":
    main()
