"""Independent instruction-level checks; no HDL simulator is needed."""

import unittest

from brightness.assembler import assemble
from brightness.kernel import build_kernel


def execute(program, pixel, index, block_dim=4):
    """Decode raw words and apply the RTL's unsigned 8-bit register semantics.

    This test oracle deliberately imports no opcode table or arithmetic helper
    from the assembler/kernel. It also observes every memory access.
    """
    registers = [0] * 16
    registers[13:] = [index // block_dim, block_dim, index % block_dim]
    memory = [0xAA] * 256
    memory[index] = pixel
    reads, writes = [], []
    for word in program:
        opcode = word >> 12
        destination = (word >> 8) & 15
        source = (word >> 4) & 15
        target = word & 15
        if opcode == 15:
            return memory, reads, writes
        if opcode == 8:
            address = registers[source]
            memory[address] = registers[target]
            writes.append(address)
            continue
        if destination >= 13:
            raise AssertionError("kernel writes a read-only register")
        if opcode == 9:
            result = word & 255
        elif opcode == 7:
            reads.append(registers[source])
            result = memory[registers[source]]
        elif opcode == 3:
            result = registers[source] + registers[target]
        elif opcode == 4:
            result = registers[source] - registers[target]
        elif opcode == 5:
            result = registers[source] * registers[target]
        elif opcode == 6:
            result = registers[source] // registers[target]
        else:
            raise AssertionError(f"unexpected opcode {opcode}")
        registers[destination] = result & 255
    raise AssertionError("kernel did not terminate with RET")


class AssemblerTests(unittest.TestCase):
    def test_known_encodings_from_rtl_isa(self):
        self.assertEqual(
            assemble("""
                ; Comments and blank lines do not consume instruction memory.
                MUL R0, %blockIdx, %blockDim
                ADD R0, R0, %threadIdx
                CONST R1, #255 ; maximum immediate
                CONST R2, #0x80
                SUB R3, R1, R2
                DIV R12, R3, R2
                LDR R4, R4
                STR R7, R6
                RET
            """),
            [0x50DE, 0x300F, 0x91FF, 0x9280, 0x4312, 0x6C32, 0x7440, 0x8076, 0xF000],
        )

    def test_numeric_special_register_aliases(self):
        self.assertEqual(assemble("MUL R0, R13, R14\nADD R0, R0, R15"), [0x50DE, 0x300F])

    def test_rejects_bad_assembly(self):
        bad_sources = [
            "", "; comment only", "NOP", "BRnzp #1", "add R0, R1, R2",
            "ADD R0 R1 R2", "ADD R0, R1", "ADD R0, R1, R2, R3",
            "ADD R00, R1, R2", "ADD R16, R1, R2", "ADD R0, R1, R16",
            "ADD R0, %unknown, R2", "ADD %threadIdx, R0, R1",
            "CONST R13, #1", "LDR R14, R0", "CONST R0, #-1",
            "CONST R0, #256", "CONST R0, #0x100", "CONST R0, #1.5",
            "CONST R0, 32", "CONST R0, #", "CONST R0, #{k}",
            "LDR R0,", "STR R0, R16", "RET R0", "RET,", "loop: RET",
        ]
        for source in bad_sources:
            with self.subTest(source=source), self.assertRaises(ValueError):
                assemble(source)
        with self.assertRaises(TypeError):
            assemble(None)

    def test_reports_source_line_and_memory_limit(self):
        with self.assertRaisesRegex(ValueError, "line 3:"):
            assemble("; first line\n\nCONST R0, #256")
        self.assertEqual(len(assemble("RET\n" * 256)), 256)
        with self.assertRaisesRegex(ValueError, "256-word"):
            assemble("RET\n" * 257)


class KernelTests(unittest.TestCase):
    def test_exhaustive_saturation_in_8bit_instruction_interpreter(self):
        for k in range(256):
            program = build_kernel(k)
            self.assertEqual(len(program), 23)
            self.assertEqual(program[-1], 0xF000)
            self.assertTrue(all(0 <= word <= 0xFFFF for word in program))
            for pixel in range(256):
                # Across each k, exercise all 128 input and output addresses.
                index = (pixel + k) % 128
                memory, reads, writes = execute(program, pixel, index)
                expected = min(255, pixel + k)
                self.assertEqual(memory[index + 128], expected, (pixel, k, index))
                self.assertEqual(memory[index], pixel, (pixel, k, index))
                self.assertEqual(reads, [index])
                self.assertEqual(writes, [index + 128])

    def test_addressing_across_block_sizes(self):
        for block_dim in (1, 2, 4, 8, 16, 32, 64, 128):
            for index in range(128):
                memory, reads, writes = execute(build_kernel(32), 240, index, block_dim)
                self.assertEqual(memory[index + 128], 255)
                self.assertEqual(reads, [index])
                self.assertEqual(writes, [index + 128])

    def test_increment_validation(self):
        class IntegerSubclass(int):
            pass

        for k in (True, False, 1.0, "1", None, IntegerSubclass(1)):
            with self.subTest(k=k), self.assertRaises(TypeError):
                build_kernel(k)
        for k in (-1, 256, 1000000):
            with self.subTest(k=k), self.assertRaises(ValueError):
                build_kernel(k)


if __name__ == "__main__":
    unittest.main()
