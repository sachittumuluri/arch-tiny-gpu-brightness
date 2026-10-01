"""Strict assembler for the eight tiny-gpu instructions used by the kernel.

Registers R0..R12 are writable; R13..R15 alias the read-only special
registers. Instructions use comma-separated operands, decimal or hexadecimal
immediates prefixed by ``#``, and optional ``;`` comments. Labels and branches
are intentionally unsupported. Encodings follow ``src/decoder.sv``.
"""

import re


_ARITHMETIC = {"ADD": 0x3, "SUB": 0x4, "MUL": 0x5, "DIV": 0x6}
_SPECIAL = {"%blockIdx": 13, "%blockDim": 14, "%threadIdx": 15}
_REGISTER = re.compile(r"R(?:[0-9]|1[0-5])\Z")
_IMMEDIATE = re.compile(r"#(?:[0-9]+|0[xX][0-9a-fA-F]+)\Z")


def _register(operand: str, *, writable: bool = False) -> int:
    if operand in _SPECIAL:
        register = _SPECIAL[operand]
    elif _REGISTER.fullmatch(operand):
        register = int(operand[1:])
    else:
        raise ValueError(f"invalid register {operand!r}")
    if writable and register > 12:
        raise ValueError(f"cannot write read-only register {operand!r}")
    return register


def _immediate(operand: str) -> int:
    if not _IMMEDIATE.fullmatch(operand):
        raise ValueError(f"expected an unsigned immediate such as #32, got {operand!r}")
    value = int(operand[1:], 16 if operand[1:].lower().startswith("0x") else 10)
    if not 0 <= value <= 255:
        raise ValueError(f"immediate must fit in 8 bits, got {value}")
    return value


def _encode(opcode: str, operands: list[str]) -> int:
    expected = 3 if opcode in _ARITHMETIC else {"CONST": 2, "LDR": 2, "STR": 2, "RET": 0}.get(opcode)
    if expected is None:
        raise ValueError(f"unsupported instruction {opcode!r}")
    if len(operands) != expected:
        raise ValueError(f"{opcode} expects {expected} operands, got {len(operands)}")
    if opcode == "RET":
        return 0xF000
    if opcode == "STR":
        return 0x8000 | (_register(operands[0]) << 4) | _register(operands[1])
    destination = _register(operands[0], writable=True)
    if opcode == "CONST":
        return 0x9000 | (destination << 8) | _immediate(operands[1])
    source = _register(operands[1])
    if opcode == "LDR":
        return 0x7000 | (destination << 8) | (source << 4)
    return (_ARITHMETIC[opcode] << 12) | (destination << 8) | (source << 4) | _register(operands[2])


def assemble(source: str) -> list[int]:
    """Assemble 1..256 instructions into 16-bit program-memory words.

    Malformed or unsupported assembly raises ``ValueError`` with its source
    line number. Invalid source types raise ``TypeError``.
    """
    if not isinstance(source, str):
        raise TypeError("assembly source must be a string")
    program = []
    for line_number, raw_line in enumerate(source.splitlines(), 1):
        line = raw_line.partition(";")[0].strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        operands = [value.strip() for value in parts[1].split(",")] if len(parts) == 2 else []
        try:
            program.append(_encode(parts[0], operands))
        except ValueError as error:
            raise ValueError(f"line {line_number}: {error}") from error
        if len(program) > 256:
            raise ValueError("program exceeds the 256-word instruction memory")
    if not program:
        raise ValueError("assembly source contains no instructions")
    return program
