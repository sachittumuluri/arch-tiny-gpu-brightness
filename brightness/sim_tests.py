"""Tests that execute real tiny-gpu RTL using cocotb and Icarus."""

import csv
import json
import os
import platform
import random
from pathlib import Path

import cocotb
from PIL import Image

from .driver import CLOCK_NS, TinyGPU

ROOT = Path(__file__).resolve().parents[1]


@cocotb.test()
async def correctness(dut):
    gpu = TinyGPU(dut)
    offsets = range(256) if os.getenv("EXHAUSTIVE_RTL") else [0, 1, 30, 50, 79, 80, 127, 128, 129, 254, 255]
    for k in offsets:
        result = await gpu.brighten(range(256), k)
        assert result.pixels == [min(255, p + k) for p in range(256)]
    rng = random.Random(26)
    for n in [1, 2, 3, 4, 5, 7, 8, 127, 128, 129, 255, 256, 257, 17 * 19]:
        pixels = [rng.randrange(256) for _ in range(n)]
        result = await gpu.brighten(pixels, 50)
        assert result.pixels == [min(255, p + 50) for p in pixels]
    dut._log.info("Correctness passed: %d brightness offsets, 14 lengths, memory guards and exact transactions", len(offsets))


@cocotb.test()
async def delayed_memory(dut):
    gpu = TinyGPU(dut, latency=5)
    pixels = [0, 205, 206, 255, 1, 254, 127, 128] * 17
    result = await gpu.brighten(pixels, 50)
    assert result.pixels == [min(255, p + 50) for p in pixels]


@cocotb.test()
async def benchmark(dut):
    gpu = TinyGPU(dut)
    result_dir = Path(os.getenv("RESULT_DIR", str(ROOT / "results")))
    result_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for pattern in ["gradient", "shapes"]:
        for size in [64, 128]:
            name = f"{pattern}_{size}"
            with Image.open(ROOT / "inputs" / f"{name}.png") as image:
                assert image.mode == "L"
                dimensions = image.size
                pixels = list(image.getdata())
            result = await gpu.brighten(pixels, 50)
            output = Image.new("L", dimensions)
            output.putdata(result.pixels)
            output.save(result_dir / f"{name}_k50.png")
            rows.append({
                "input": name, "width": size, "height": size, "pixels": len(pixels),
                "k": 50, "launches": result.launches, "launched_threads": result.launched_threads,
                "kernel_cycles": result.kernel_cycles, "setup_cycles": result.setup_cycles,
                "clock_period_ns": CLOCK_NS, "kernel_time_us": result.kernel_cycles * CLOCK_NS / 1000,
                "cycles_per_pixel": result.kernel_cycles / len(pixels),
                "simulator_wall_seconds": round(result.wall_seconds, 6), "correct": True,
            })
            dut._log.info("%s: %d cycles, %.3f ms simulated, %.2f s wall time", name,
                          result.kernel_cycles, result.kernel_cycles * CLOCK_NS / 1e6, result.wall_seconds)
    with (result_dir / "benchmark.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (result_dir / "benchmark.json").write_text(json.dumps({
        "configuration": {"cores": 2, "threads_per_block": 4, "data_channels": 4,
                          "program_channels": 1, "memory_response_cycles": 1,
                          "tile_pixels": 128, "clock_period_ns": CLOCK_NS,
                          "python": platform.python_version(), "cocotb": cocotb.__version__,
                          "host": f"{platform.system()} {platform.release()} {platform.machine()}"},
        "timing_note": "Kernel cycles count start through done for each launch; exclude 5 setup cycles/launch and host transfer time. Clock is an assumption, not an achieved silicon frequency. Wall time includes driver and verification, excludes compilation and simulator startup.",
        "results": rows,
    }, indent=2) + "\n")


@cocotb.test()
async def custom_image(dut):
    with Image.open(os.environ["INPUT_IMAGE"]) as image:
        image = image.convert("L")
        dimensions, pixels = image.size, list(image.getdata())
    result = await TinyGPU(dut).brighten(pixels, int(os.environ.get("BRIGHTNESS_K", "50")))
    output = Image.new("L", dimensions)
    output.putdata(result.pixels)
    destination = Path(os.environ["OUTPUT_IMAGE"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    output.save(destination)
    dut._log.info("Saved %s: %d pixels, %d launches, %d cycles", destination,
                  len(pixels), result.launches, result.kernel_cycles)
