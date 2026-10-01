#!/usr/bin/env python3
"""Compile RTL, run selected cocotb tests, and propagate XML failures to the shell."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=["test", "exhaustive", "benchmark", "matadd", "matmul", "image"])
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--k", type=int, default=50)
    args = parser.parse_args()
    # Relative paths belong to the caller, even when the script lives elsewhere.
    if args.input:
        args.input = args.input.resolve()
    if args.output:
        args.output = args.output.resolve()
    for binary in ["sv2v", "iverilog", "vvp"]:
        if not shutil.which(binary):
            parser.error(f"missing {binary}; see README setup instructions")
    if not 0 <= args.k <= 255:
        parser.error("--k must be in 0..255")
    if args.suite == "image" and (not args.input or not args.output):
        parser.error("image requires --input and --output")
    os.chdir(ROOT)
    if sys.prefix != sys.base_prefix:
        os.environ["VIRTUAL_ENV"] = sys.prefix
    from cocotb.runner import get_runner

    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    converted = subprocess.run(["sv2v", *map(str, sorted((ROOT / "src").glob("*.sv")))],
                               check=True, capture_output=True, text=True)
    (build / "gpu.v").write_text(converted.stdout)
    runner = get_runner("icarus")
    runner.build(sources=[build / "gpu.v"], hdl_toplevel="gpu", build_dir=build / "sim",
                 always=True, timescale=("1ns", "1ns"))
    module, testcase = "brightness.sim_tests", None
    env = {"PYTHONPATH": str(ROOT), "EXHAUSTIVE_RTL": ""}
    if args.suite in ["matadd", "matmul"]:
        module = f"test.test_{args.suite}"
    elif args.suite in ["test", "exhaustive"]:
        testcase = "correctness,delayed_memory"
        if args.suite == "exhaustive":
            env["EXHAUSTIVE_RTL"] = "1"
    elif args.suite == "benchmark":
        testcase = "benchmark"
    else:
        testcase = "custom_image"
        env.update(INPUT_IMAGE=str(args.input.resolve()), OUTPUT_IMAGE=str(args.output.resolve()),
                   BRIGHTNESS_K=str(args.k))
    results_xml = build / f"{args.suite}.xml"
    results_xml.unlink(missing_ok=True)
    runner.test(hdl_toplevel="gpu", test_module=module, testcase=testcase, test_dir=ROOT,
                extra_env=env, results_xml=str(results_xml))
    cases = ET.parse(results_xml).findall(".//testcase")
    expected_count = 2 if args.suite in ["test", "exhaustive"] else 1
    if len(cases) != expected_count or any(case.find("failure") is not None or case.find("error") is not None
                        or case.find("skipped") is not None for case in cases):
        raise SystemExit(f"simulation failed; see {results_xml}")
    print(f"PASS: {len(cases)} RTL test(s); {results_xml.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
