# Image brightness on tiny-gpu

A complete solution to the [ARCH Lab undergraduate image-processing task](https://archlabs.us/apply/task26ug/). A 23-instruction kernel runs on the original tiny-gpu RTL and computes:

```text
output[x, y] = min(255, input[x, y] + k)
```

It accepts any positive image dimensions and an integer brightness increment `0 ≤ k ≤ 255`. Each thread reads one grayscale pixel, computes the saturated result, and writes it to a separate output buffer. Large images are tiled through the GPU's existing 256-byte memory. The host assembles instructions, transfers tiles, and checks results; the brightness computation runs in the simulated GPU.

## Run it

Tested locally with Python 3.9.6, cocotb 1.9.2, Icarus Verilog 13.0, and sv2v 0.0.13 on macOS arm64. Python 3.9–3.12 is recommended for these pinned dependencies.

```sh
# macOS prerequisites
brew install icarus-verilog sv2v

git clone https://github.com/sachittumuluri/arch-tiny-gpu-brightness.git
cd arch-tiny-gpu-brightness
make setup

# Original examples, unit tests, hardware tests, and four image benchmarks
make all
```

On Linux, install Icarus Verilog (`sudo apt-get install iverilog`) and put the [sv2v 0.0.13 release binary](https://github.com/zachjs/sv2v/releases/tag/v0.0.13) on `PATH`. Then use the same `make setup` and `make all` commands. The [GitHub Actions workflow](.github/workflows/test.yml) provides the exact Ubuntu setup.

Individual commands:

| Command | Purpose |
| --- | --- |
| `make test_matadd test_matmul` | Run both original upstream examples |
| `make test` | Exhaustive arithmetic/encoding unit tests, representative RTL tests, delayed-memory test |
| `make exhaustive` | Run all 65,536 pixel/increment pairs on the RTL as well |
| `make benchmark` | Simulate both fixtures at 64×64 and 128×128; save PNG outputs and measured CSV/JSON |
| `make inputs` | Regenerate the original deterministic input fixtures |

To process your own image through the simulator:

```sh
.venv/bin/python scripts/run_sim.py image \
  --input inputs/shapes_128.png --output build/my_brightened.png --k 50
```

Color inputs are converted to 8-bit grayscale before simulation. Each simulation has a per-launch cycle timeout; failed assertions and missing test results cause the command to fail. Do not run multiple simulation commands concurrently in one checkout because they share a build directory.

## Design

The original GPU has two cores, four threads per block, four data-memory channels, one instruction-memory channel, 8-bit arithmetic, and 8-bit data addresses. The RTL in `src/` is unchanged from upstream commit [`02b6c2c`](https://github.com/adam-maj/tiny-gpu/tree/02b6c2ce223f606051a6d3a35ca942fbb1dffde2).

**Mapping:** flatten the image in row-major order. For each tile, thread index `i = blockIdx * blockDim + threadIdx` loads address `i` and stores address `128 + i`. A tile contains up to 128 actual pixels. The final tile is padded to a multiple of four; padded outputs are discarded. This accommodates the upstream scheduler's use of the last lane's program counter. Reset the GPU and load the thread count before each launch.

**Clamping:** simply adding `k` would wrap at 256, while pixel-dependent branches would diverge within a block. The kernel instead computes an overflow flag with ordinary arithmetic:

```text
h       = (p // 2) + (k // 2) + (p % 2) * (k % 2)   # floor((p+k)/2), at most 255
carry   = h // 128                                  # 0 or 1
wrapped = (p + k) % 256
result  = wrapped + carry * (255 - wrapped)
```

Every intermediate fits in eight bits except the deliberately wrapping `ADD`. This works for the entire `0..255` increment range, including `k=0`, exact sums of 255, and overflow. All lanes follow the same 23 instructions. See the annotated [assembly](kernels/brightness.asm), [design explanation and proof](docs/DESIGN.md), and [interview walkthrough](docs/INTERVIEW_GUIDE.md).

## Results and validation

All 65,536 pixel/increment combinations passed on the actual RTL, in addition to the independent software interpreter. The original examples, boundary/tiling tests, delayed-memory checks, and four image benchmarks also passed. See [recorded validation and simulator reports](results/VALIDATION.md).

The [performance report](results/REPORT.md) contains measured cycle counts, simulator wall times, before/after images, and timing assumptions. Raw records are in [benchmark.csv](results/benchmark.csv) and [benchmark.json](results/benchmark.json).

| Image size | Pixels | Measured kernel cycles | Simulated time at 10 ns/clock |
| --- | ---: | ---: | ---: |
| 64×64 | 4,096 | 125,664 | 1.25664 ms |
| 128×128 | 16,384 | 502,656 | 5.02656 ms |

The measured kernel cycle count grows exactly fourfold when pixel count grows fourfold.

The benchmarks use `k=50`, two original image patterns, 128-pixel tiles, and a one-cycle external-memory response. A 64×64 image requires 32 launches; a 128×128 image requires 128 launches. Simulated time is derived from measured clock cycles using an assumed 10 ns clock. It is not a measured physical-device frequency or a CPU/GPU speed comparison. Five setup cycles per launch and unmodeled host transfer time are excluded from kernel time and identified separately in the report.

Correctness checks include:

- Every pixel value and every increment: 65,536 cases in an independent instruction interpreter; `make exhaustive` performs the same coverage on the RTL.
- RTL regression across 11 increments, 14 lengths (including 1, 3, 127, 128, 129, 257 and a 17×19 image), mixed saturating/non-saturating lanes, and five-cycle memory responses.
- Exactly one input read and one output write per launched thread; unchanged input memory and untouched output guard bytes.
- Exact byte-for-byte output comparison with the Python reference for every simulated tile and benchmark image.

## What limits scaling?

Memory holds only 128 input and 128 output bytes; the thread count and internal address/register paths are eight bits. Increasing a top-level parameter alone cannot make the GPU hold an entire large image. Tiling keeps the hardware unchanged but adds launches and host transfers. Instruction fetches share one channel, scheduling has no latency-hiding warp switching, and the 23-instruction clamp costs more than a native saturating-add instruction would. The design deliberately avoids divergent branches and unsupported partial blocks. The [design notes](docs/DESIGN.md) discuss these trade-offs and simulator portability.

## Repository map

| Path | Contents |
| --- | --- |
| `kernels/brightness.asm` | Commented GPU kernel template |
| `brightness/assembler.py`, `brightness/kernel.py` | Strict assembler and brightness-constant substitution |
| `brightness/driver.py` | Cocotb host, tiling, external memory model, cycle measurements |
| `brightness/sim_tests.py`, `tests/test_kernel.py` | RTL and independent software tests |
| `inputs/`, `scripts/generate_inputs.py` | Reproducible original grayscale inputs and provenance |
| `results/` | Actual simulator outputs and performance evaluation |
| `src/`, `test/` | Original tiny-gpu RTL and example testbenches |
| `docs/` | Design, interview guide, preserved upstream README and Makefile |

## Attribution

Based on [Adam Majmudar's tiny-gpu](https://github.com/adam-maj/tiny-gpu), with its original Git history and RTL retained. The original documentation is preserved in [docs/UPSTREAM.md](docs/UPSTREAM.md). New additions comprise the brightness kernel, assembler, driver, tests, fixtures, evaluation, and documentation. This solution was developed with AI assistance; the [interview guide](docs/INTERVIEW_GUIDE.md) explains the implementation and decisions for review and demonstration. No license has been added to the upstream material.
