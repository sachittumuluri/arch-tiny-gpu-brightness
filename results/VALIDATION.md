# Recorded validation

Executed on 2026-10-01 using the unchanged tiny-gpu RTL at upstream commit `02b6c2ce223f606051a6d3a35ca942fbb1dffde2` and the brightness implementation in commit `9def1b8`.

Environment: macOS arm64 (Darwin 24.1.0), Python 3.9.6, cocotb 1.9.2, Icarus Verilog 13.0, sv2v 0.0.13.

| Check | Result | Evidence |
| --- | --- | --- |
| `make unit` | 7 passed, including all 65,536 pixel/increment combinations | [Independent interpreter and tests](../tests/test_kernel.py) |
| `make test_matadd` | Passed | [JUnit XML](validation/matadd.xml) |
| `make test_matmul` | Passed | [JUnit XML](validation/matmul.xml) |
| `make rtl` | 2 passed: representative correctness and delayed memory | [JUnit XML](validation/test.xml) |
| `make benchmark` | All four images correct | [JUnit XML](validation/benchmark.xml), [measured report](REPORT.md) |
| `make exhaustive` | 2 passed: all 65,536 pixel/increment pairs on actual RTL, 14 additional lengths, and delayed memory | [JUnit XML](validation/exhaustive.xml) |
| Custom-image CLI from outside the repository | Passed; a 3×1 image `[0,205,255]` with `k=50` produced `[50,255,255]` at the requested relative output path | [JUnit XML](validation/image.xml) |
| Clean Ubuntu 24.04 / Python 3.11.16 workflow | Passed; all four benchmark cycle counts exactly reproduce the local results | [Successful Linux run](https://github.com/sachittumuluri/arch-tiny-gpu-brightness/actions/runs/36925145797) |

The XML files record actual completed simulations; only their absolute source-file paths were made repository-relative. Runtime and simulated-time fields are retained. The exhaustive RTL sweep took about 223 seconds on this host. Every tile also checks input preservation, output guards, exact memory transaction counts, and padded-lane results.

The [Linux workflow](../.github/workflows/test.yml) runs the original examples, the normal test suite, and all four benchmarks from a clean checkout. Its current result is visible in [GitHub Actions](https://github.com/sachittumuluri/arch-tiny-gpu-brightness/actions). It does not run the longer exhaustive RTL sweep by default.
