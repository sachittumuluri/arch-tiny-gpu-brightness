# Brightness kernel design

This implementation executes `output[i] = min(255, input[i] + k)` on the original tiny-gpu RTL. Pixels and `k` are unsigned integers in `0..255`. The host loads tiles and collects output; the simulated GPU performs the pixel arithmetic and stores every result.

The hardware sources in [`src/`](../src/) retain their original eight-bit datapath and addressing. The addition is expressed using the existing ISA, without adding an instruction or changing the ALU.

## Data flow and thread mapping

```text
Grayscale image → flatten pixels → tiles of at most 128 pixels
                                         ↓
                          reset GPU and load tile/program
                                         ↓
                         tiny-gpu executes brightness.asm
                                         ↓
                          read output addresses 128..255
                                         ↓
                            concatenate → output image
```

Each thread computes its local pixel index as:

```text
i = blockIdx * blockDim + threadIdx
```

The default GPU has two cores and four threads per block, so up to eight threads execute concurrently. Each core runs one four-thread block at a time. A full tile launches 128 threads in 32 blocks; each thread loads address `i` and writes address `128 + i`.

| Resource | Allocation or limit |
| --- | --- |
| Data memory | 256 eight-bit words |
| Tile input | Addresses `0..127` |
| Tile output | Addresses `128..255` |
| Device thread count | Eight bits; this driver launches `4..128` threads |
| Program memory | 256 sixteen-bit instructions, eight-bit addresses |
| Brightness program | 23 instructions for every supported `k` |
| Data memory channels | Four |
| Program memory channels | One |

The partition keeps input and output separate and fits the existing address space exactly. For a full tile, `blockIdx` is at most 31, the local index is at most 127, and the output address is at most 255. A 64×64 image needs 32 launches; a 128×128 image needs 128 launches.

The final tile is zero-padded to a whole block of four. Only the original pixels are copied into the image. This matters because the stock scheduler advances the core using the last lane's next program counter. Leaving that lane disabled in a partial block would make its PC unsuitable for advancing the block. Padding avoids relying on partial-block execution.

Every launch resets the GPU. The dispatcher keeps completion state and counters until reset, so toggling `start` alone is insufficient to launch another tile. Four reset clocks also flush the registered links between the memory controllers and cores.

## Saturation with eight-bit arithmetic

An ordinary eight-bit addition wraps: `240 + 50` becomes 34. Testing the wrapped sum against 255 cannot recover the lost carry. Pixel-dependent branches also cannot be used here: the stock scheduler assumes all lanes in a block follow the same control flow.

The kernel detects the carry before performing the wrapping addition. Write:

```text
p = 2a + r, where a = floor(p/2) and r = p mod 2
k = 2b + s, where b = floor(k/2) and s = k mod 2
```

Since `r` and `s` are each zero or one, `floor((r+s)/2) = r*s`. Therefore:

```text
h = a + b + r*s = floor((p+k)/2)
c = floor(h/128)
w = (p+k) mod 256
result = w + c*(255-w)
```

All carry-detection intermediates fit eight bits: `a` and `b` are at most 127, `a+b` is at most 254, and `h` is at most 255. Thus `c` is exactly zero or one. When `p+k < 256`, `c=0` and the result is the sum. When `p+k >= 256`, `c=1` and the result is 255. A sum of exactly 255 correctly remains 255 with no carry.

For `p=240, k=50`, `h=120+25=145`, `c=1`, `w=34`, and the correction is `255-34=221`. The final result is 255. Both `k=0` and `k=255` use the same instruction sequence, with divisors fixed at two and 128.

[`kernels/brightness.asm`](../kernels/brightness.asm) contains the complete 23-instruction program: six constants, fourteen arithmetic instructions, one load, one store, and one return. [`brightness/kernel.py`](../brightness/kernel.py) substitutes `k`, `floor(k/2)`, and `k mod 2` into the constants. Program length and control flow do not depend on pixel values or `k`.

The assembler in [`brightness/assembler.py`](../brightness/assembler.py) implements the eight instruction types used by this program. It follows the decoder's sixteen-bit encodings and rejects invalid operands, writes to special registers, out-of-range immediates, and programs exceeding instruction memory. It does not implement labels or branches.

## Simulation and memory behavior

[`scripts/run_sim.py`](../scripts/run_sim.py) converts the original SystemVerilog with sv2v, compiles it with Icarus Verilog, and runs cocotb against the resulting GPU simulation. Output images are built from memory words written by the RTL. The Python reference calculation only checks those words; it does not generate the GPU output.

The external-memory model in [`brightness/driver.py`](../brightness/driver.py) services one program channel and four data channels. Channel zero occupies the least significant packed bits produced by sv2v. A request stays valid while the controller waits for its response. The model keeps `ready` asserted until `valid` drops, checks address/data stability, and counts or commits each transaction only once. This prevents a multi-cycle handshake from being counted as repeated reads or writes.

Default response latency is one clock: a request visible after a rising edge receives its response before the next rising edge. The delayed-memory test uses five clocks. Controller arbitration, internal pipeline registers, fetch/decode stages, and waiting for all lane requests add further cycles to instruction execution; one-clock external response does not mean one-clock load instructions.

For each tile the driver verifies:

- Every launched thread loads exactly its input address and stores exactly its output address.
- Output equals the reference, including any padded lanes.
- Input memory is unchanged.
- Output addresses beyond the launched threads retain their sentinel value.

## What the measurements mean

The benchmark processes the gradient and shapes fixtures at 64×64 and 128×128 with `k=50`. Running `make benchmark` produces `results/benchmark.csv`, `results/benchmark.json`, and four output images. Those files contain measured results; this design document does not prescribe cycle counts.

| Field | Meaning |
| --- | --- |
| `kernel_cycles` | Sum of rising edges from asserting `start` through observing `done`, inclusive, across all launches |
| `setup_cycles` | Five clocks per launch: four for reset, one to write the device thread count |
| `kernel_time_us` | `kernel_cycles × 10 ns / 1000`, using the simulation's chosen clock period |
| `cycles_per_pixel` | `kernel_cycles / original_pixel_count` |
| `simulator_wall_seconds` | Host elapsed time inside `brighten`, including tile preparation and verification |

Kernel cycles exclude setup, host memory transfers, program assembly, image decoding/encoding, compilation, and simulator startup. Adding `setup_cycles` gives the clocked setup-plus-execution total for this model, not an end-to-end hardware runtime. Wall time also excludes program construction before its timer, image file work, compilation, and simulator startup. It depends on the host machine and software environment.

The 10 ns period is an assumption used to convert cycles to simulated time. No synthesis or timing closure establishes a 100 MHz implementation. In particular, the stock ALU's multiplication and division execute in a single RTL execution stage, whose physical timing is not evaluated here. Host memory loading is a direct change to the Python memory model; there is no simulated DMA engine or transfer bandwidth.

Both required image sizes comprise full tiles and execute the same program, so identical simulator configuration should give the same cycles per full tile. The larger image requires four times as many launches. Pixel content does not change instruction count or memory addresses.

## Verification and retained limitations

`make unit` runs an independent instruction interpreter over every one of the 65,536 pixel/`k` pairs, checking encodings, output, and memory addresses. `make rtl` exercises actual RTL with representative boundary increments, every pixel value for those increments, varied lengths, padding, and delayed memory. `make exhaustive` extends the RTL increment sweep to all 256 values. The interpreter and RTL simulations are separate levels of verification.

The upstream matrix programs remain available through `make test_matadd` and `make test_matmul`. Test commands report failures through their exit status; stored simulator XML reports record the specific run.

Several stock limitations remain intentional:

- Address, register, ALU, LSU, and thread-control paths contain hard-coded eight-bit widths. Changing top-level memory parameters alone cannot make the GPU process a full image in one launch.
- Branch divergence and partially active final blocks are not repaired. This kernel uses no branches and the host launches complete blocks.
- The existing `CMP` implementation has unsigned-subtraction and flag-ordering issues. This kernel does not use it.
- The scheduler initializes a local `any_lsu_waiting` variable at its declaration. Static initialization semantics can be problematic in a direct SystemVerilog flow. In the installed sv2v flow, conversion emits an assignment inside each execution of the WAIT block, so the generated simulation code reevaluates the flag correctly. This is a tool-flow observation, not a claim that the source was fixed.
- The simulation does not add a cache, memory coalescing, DMA, branch masking, wider arithmetic, or a physical implementation flow.

For an interview-oriented walkthrough, see [`INTERVIEW_GUIDE.md`](INTERVIEW_GUIDE.md).
