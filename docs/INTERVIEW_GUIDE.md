# Interview walkthrough

This project runs an unsigned grayscale brightness operation on the original eight-bit tiny-gpu: `out[i] = min(255, in[i] + k)`. The main design decisions are a branchless saturation formula and host tiling that respects the hardware's 256-word data memory. The checked-in work can be explained from the assembly through the actual RTL simulation without claiming a hardware change.

## A short explanation

1. The host flattens a grayscale image and loads up to 128 pixels into addresses `0..127`. The other 128 addresses hold the output.
2. A thread computes `i = blockIdx*blockDim + threadIdx`, loads one pixel, calculates a saturated sum, and stores to `128+i`.
3. Saturation detects carry using `h = floor(p/2) + floor(k/2) + (p mod 2)*(k mod 2)`. This equals `floor((p+k)/2)` and fits eight bits. `h//128` says whether the original sum exceeded 255.
4. The GPU executes the same 23 instructions for every pixel. The host reads back GPU-written output, checks it against a reference, and repeats for the next tile.
5. Benchmarks report actual start-to-done simulator cycles separately from setup and host wall time. A chosen 10 ns clock period is not evidence of physical timing closure.

## Files worth opening

| File | What to explain |
| --- | --- |
| [`kernels/brightness.asm`](../kernels/brightness.asm) | Thread addressing, carry calculation, load/store, fixed instruction path |
| [`brightness/assembler.py`](../brightness/assembler.py) | Mapping the ISA into sixteen-bit words and rejecting malformed input |
| [`brightness/driver.py`](../brightness/driver.py) | Tile loading, launch/reset sequence, memory handshake, cycle counting |
| [`brightness/sim_tests.py`](../brightness/sim_tests.py) | Boundary coverage, delayed memory, fixtures and benchmark outputs |
| [`src/scheduler.sv`](../src/scheduler.sv) | Instruction stages and the shared-control-flow limitation |
| [`src/controller.sv`](../src/controller.sv) | Arbitration between consumers and external memory channels |

[`DESIGN.md`](DESIGN.md) contains the complete proof, resource limits, and measurement definitions.

## Reproduce the work

Run these commands from the repository root after installing `sv2v`, `iverilog`, and `vvp` as described in the main README:

```sh
make setup
make unit
make rtl
make benchmark
```

`make unit` checks all pixel/increment combinations in an independent instruction interpreter. `make rtl` checks the real GPU on boundary increments, every pixel value for those increments, varied lengths, and delayed memory. `make benchmark` runs both supplied patterns at both requested sizes and writes images plus CSV/JSON measurements into `results/`.

Additional commands:

```sh
# All 256 increments × all 256 pixel values on actual RTL, plus other checks.
make exhaustive

# Original upstream matrix kernels.
make test_matadd
make test_matmul

# Recreate the deterministic input fixtures.
make inputs

# Run a supplied image with a chosen increment; input is converted to grayscale.
.venv/bin/python scripts/run_sim.py image \
  --input inputs/gradient_64.png \
  --output results/custom_k80.png \
  --k 80
```

Use the produced benchmark files when discussing measured numbers. Confirm which test commands completed and examine their simulator XML reports in `build/`; distinguish the exhaustive interpreter check from the optional exhaustive RTL run.

## Questions to prepare for

**Why not add `k` and compare the result with 255?**

The ALU discards carry when storing an eight-bit sum. For example, `240+50` wraps to 34, so the final eight-bit value cannot reveal overflow on its own. The kernel computes carry from the halves before using the wrapping sum.

**Why does the carry formula work?**

Let `p=2a+r` and `k=2b+s`, with `r,s` each zero or one. Then `floor((p+k)/2)=a+b+floor((r+s)/2)=a+b+r*s`. This value is at most 255. Dividing it by 128 yields one exactly when `p+k >= 256`. A wrapped sum `w` is corrected by `w+c*(255-w)`, producing either `w` or 255.

**Why avoid branches?**

The stock scheduler has one instruction stream per core and takes the next PC from its last lane. Different pixels in one block can require different saturation decisions, so branching on each pixel's value would violate the scheduler's convergence assumption. Arithmetic selection keeps every lane on the same path.

**Why 128 pixels per tile?**

The GPU has 256 eight-bit data addresses. Keeping a separate input and output region gives 128 pixels per tile and avoids changing the RTL. That also fits the eight-bit thread-count register. A 64×64 image needs 32 launches; a 128×128 image needs 128.

**Why pad to four threads?**

Four is the hardware block size. The scheduler chooses the last lane's PC even when that lane is inactive, so partial blocks are unsafe in the retained implementation. Zero-padding enables all four lanes in the last block; padded outputs are checked and then discarded.

**Does Python perform the brightness computation?**

Python loads pixels, assembles constants, models external memory, and verifies output. The saved output comes from addresses written by the simulated RTL. The reference expression is used only for assertions. Exact read/write counts and memory sentinels further check the GPU's behavior.

**How much runs in parallel?**

The default configuration has two cores with four lanes each. At most eight threads execute concurrently. Each core processes its blocks sequentially, and four external data channels service requests from all eight lanes. Program fetches share one channel. A 128-thread launch does not imply 128 simultaneous hardware lanes.

**What does the reported runtime include?**

Kernel cycles count rising edges from `start` through the edge after which `done` is observed, summed across tiles. They exclude five setup clocks per launch: four reset clocks and one thread-count write. The modeled 10 ns clock converts cycles to simulated time. Host wall time measures the driver and verification loop and is a separate quantity. Neither figure includes a modeled DMA transfer or establishes a real device's clock rate.

**Should image content affect cycles?**

Not in this configuration: all pixels follow the same 23 instructions, access the same per-thread addresses, and use the same fixed memory-response latency. Four times as many full tiles should produce four times the kernel cycles. Check the measured CSV before quoting exact counts.

**What changes would improve performance?**

Potential improvements include wider addressing and thread control to reduce launches, memory coalescing, instruction caching, or a saturating-add/select instruction to shorten the kernel. Each changes the architecture and needs its own correctness and timing validation. The current implementation intentionally demonstrates the operation using the existing ISA and eight-bit hardware.

**What are the most important remaining limitations?**

The design retains the original branch behavior, eight-bit internal widths, and the stock comparison issue. It relies on the documented sv2v conversion flow for the scheduler's local initialization behavior. The memory model is functional rather than a physical memory system, and no synthesis or timing closure was performed. The supported increment is an integer in `0..255`; negative adjustments are outside this kernel's contract.
