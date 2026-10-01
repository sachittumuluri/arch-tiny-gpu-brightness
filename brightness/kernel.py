"""Build a branchless, saturating brightness kernel for 8-bit tiny-gpu."""

from pathlib import Path

from .assembler import assemble


_TEMPLATE = Path(__file__).resolve().parent.parent / "kernels" / "brightness.asm"


def build_kernel(k: int) -> list[int]:
    """Return the 23 instruction words implementing ``min(255, pixel + k)``.

    ``k`` must be a Python integer in 0..255 (booleans are rejected). A launch
    processes at most 128 pixels: inputs occupy addresses 0..127, and outputs
    occupy 128..255. The host controls the actual number of active threads.
    """
    if type(k) is not int:
        raise TypeError("brightness increment k must be an integer")
    if not 0 <= k <= 255:
        raise ValueError("brightness increment k must be in 0..255")
    source = _TEMPLATE.read_text(encoding="utf-8").format(k=k, half_k=k // 2, odd_k=k % 2)
    return assemble(source)
