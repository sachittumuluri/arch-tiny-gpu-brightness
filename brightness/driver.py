"""Cocotb host driver for the unmodified, sv2v-flattened tiny-gpu RTL."""

from collections import Counter
from dataclasses import dataclass
from time import perf_counter

from cocotb.triggers import Timer

from .kernel import build_kernel

TILE_PIXELS = 128
BLOCK_SIZE = 4
CLOCK_NS = 10


class ExternalMemory:
    """Level handshake memory, responding after `latency` clock cycles.

    sv2v packs channel zero into the least significant bits. Requests are
    counted/committed once; ready stays high until valid goes low.
    """

    def __init__(self, dut, name, channels, width, latency=1):
        if type(latency) is not int or latency < 1:
            raise ValueError("memory latency must be a positive integer")
        self.channels, self.width, self.latency = channels, width, latency
        self.words = [0] * 256
        self.reads, self.writes = Counter(), Counter()
        self.ports, self.pending = {}, {}
        for operation in (["read"] if name == "program" else ["read", "write"]):
            self.ports[operation] = {
                field: getattr(dut, f"{name}_mem_{operation}_{field}")
                for field in ["valid", "address", "ready", "data"]
            }
            self.pending[operation] = [None] * channels
        self.clear_bus()

    def clear_bus(self):
        for operation, ports in self.ports.items():
            ports["ready"].value = 0
            if operation == "read":
                ports["data"].value = 0
            self.pending[operation] = [None] * self.channels

    def step(self):
        for operation, ports in self.ports.items():
            valid = int(ports["valid"].value)
            addresses = int(ports["address"].value)
            write_data = int(ports["data"].value) if operation == "write" else 0
            ready, read_data = 0, 0
            for channel in range(self.channels):
                if not (valid >> channel) & 1:
                    self.pending[operation][channel] = None
                    continue
                address = (addresses >> (8 * channel)) & 255
                data = (write_data >> (self.width * channel)) & ((1 << self.width) - 1)
                request = self.pending[operation][channel]
                if request is None:
                    request = [address, data, self.latency, False]
                    self.pending[operation][channel] = request
                assert request[0] == address, "address changed before valid dropped"
                if operation == "write":
                    assert request[1] == data, "write data changed before valid dropped"
                request[2] -= 1
                if request[2] <= 0:
                    ready |= 1 << channel
                    if not request[3]:
                        if operation == "write":
                            self.words[address] = data
                            self.writes[address] += 1
                        else:
                            self.reads[address] += 1
                        request[3] = True
                    if operation == "read":
                        read_data |= self.words[address] << (self.width * channel)
            ports["ready"].value = ready
            if operation == "read":
                ports["data"].value = read_data


@dataclass
class RunResult:
    pixels: list
    kernel_cycles: int
    setup_cycles: int
    launches: int
    launched_threads: int
    wall_seconds: float


class TinyGPU:
    def __init__(self, dut, latency=1):
        self.dut = dut
        dut.clk.value = 0
        dut.reset.value = 1
        dut.start.value = 0
        dut.device_control_write_enable.value = 0
        dut.device_control_data.value = 0
        self.program = ExternalMemory(dut, "program", 1, 16, latency)
        self.data = ExternalMemory(dut, "data", 4, 8, latency)

    async def tick(self, service=True):
        # Drive memory before the rising edge; inspect after synchronous logic settles.
        self.dut.clk.value = 0
        await Timer(CLOCK_NS // 2, units="ns")
        if service:
            self.program.step()
            self.data.step()
        self.dut.clk.value = 1
        await Timer(CLOCK_NS // 2, units="ns")

    async def launch(self, program, memory, threads, timeout=100_000):
        if not 4 <= threads <= TILE_PIXELS or threads % BLOCK_SIZE:
            raise ValueError("launches require 4..128 threads in complete blocks of four")
        self.dut.start.value = 0
        self.dut.reset.value = 1
        self.dut.device_control_write_enable.value = 0
        self.program.clear_bus()
        self.data.clear_bus()
        # Flush the registered controller-to-core connections, too.
        for _ in range(4):
            await self.tick(service=False)
        self.program.words = list(program) + [0] * (256 - len(program))
        self.data.words = list(memory)
        self.data.reads.clear()
        self.data.writes.clear()
        self.program.reads.clear()
        self.dut.reset.value = 0
        self.dut.device_control_data.value = threads
        self.dut.device_control_write_enable.value = 1
        await self.tick()
        self.dut.device_control_write_enable.value = 0
        self.dut.start.value = 1
        # Rising edges from start assertion through observation of done.
        for cycles in range(1, timeout + 1):
            await self.tick()
            if int(self.dut.done.value):
                self.dut.start.value = 0
                return cycles
        raise AssertionError(f"GPU did not finish {threads} threads in {timeout} cycles")

    async def brighten(self, pixels, k):
        program = build_kernel(k)
        pixels = list(pixels)
        if not pixels or any(type(p) is not int or not 0 <= p <= 255 for p in pixels):
            raise ValueError("pixels must be a nonempty sequence of integers in 0..255")
        started = perf_counter()
        output, cycles, launches, launched = [], 0, 0, 0
        for offset in range(0, len(pixels), TILE_PIXELS):
            tile = pixels[offset:offset + TILE_PIXELS]
            threads = ((len(tile) + BLOCK_SIZE - 1) // BLOCK_SIZE) * BLOCK_SIZE
            input_memory = tile + [0] * (TILE_PIXELS - len(tile))
            memory = input_memory + [165] * TILE_PIXELS
            cycles += await self.launch(program, memory, threads)
            actual = self.data.words[TILE_PIXELS:TILE_PIXELS + threads]
            # Reference arithmetic validates results; it never writes GPU output.
            expected = [min(255, p + k) for p in input_memory[:threads]]
            assert actual == expected, f"pixel mismatch in tile at offset {offset}"
            assert self.data.words[:TILE_PIXELS] == input_memory, "input was overwritten"
            assert self.data.words[TILE_PIXELS + threads:] == [165] * (TILE_PIXELS - threads)
            assert self.data.reads == Counter(range(threads)), "unexpected input reads"
            assert self.data.writes == Counter(range(TILE_PIXELS, TILE_PIXELS + threads)), "unexpected output writes"
            output.extend(actual[:len(tile)])
            launches += 1
            launched += threads
        return RunResult(output, cycles, 5 * launches, launches, launched, perf_counter() - started)
