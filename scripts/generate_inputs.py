#!/usr/bin/env python3
"""Create deterministic, original grayscale test images for brightness +50."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


# The values next to 205 exercise the saturation boundary for brightness +50.
PROBE_VALUES = (0, 1, 49, 50, 127, 204, 205, 206, 254, 255)


def add_probe_strip(image: Image.Image) -> None:
    """Put ten uniform intensity swatches along the bottom eighth of an image."""
    width, height = image.size
    pixels = image.load()
    for y in range(height - height // 8, height):
        for x in range(width):
            pixels[x, y] = PROBE_VALUES[min(x * len(PROBE_VALUES) // width, 9)]


def gradient(size: int) -> Image.Image:
    """Horizontal black-to-white ramp, with saturation probes at the bottom."""
    image = Image.new("L", (size, size))
    # Integer rounding avoids dependence on floating-point implementations.
    row = [(255 * x + (size - 1) // 2) // (size - 1) for x in range(size)]
    image.putdata(row * size)
    add_probe_strip(image)
    return image


def shapes(size: int) -> Image.Image:
    """High-contrast geometry over a vertical dark-to-mid-gray background."""
    image = Image.new("L", (size, size))
    image.putdata([
        24 + (96 * y) // (size - 1)
        for y in range(size)
        for _x in range(size)
    ])
    draw = ImageDraw.Draw(image)
    unit = size // 16
    draw.rectangle((unit, unit, 7 * unit, 7 * unit), fill=204, outline=255,
                   width=unit)
    draw.ellipse((9 * unit, unit, 15 * unit, 7 * unit), fill=205, outline=0,
                 width=unit)
    draw.polygon(((unit, 13 * unit), (5 * unit, 8 * unit), (8 * unit, 13 * unit)),
                 fill=206)
    draw.rectangle((10 * unit, 9 * unit, 14 * unit, 12 * unit), fill=254)
    draw.line((0, 8 * unit, size - 1, 8 * unit), fill=50, width=unit)
    add_probe_strip(image)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path(__file__).resolve().parents[1] / "inputs",
        help="destination directory (default: repository inputs/)",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, create in (("gradient", gradient), ("shapes", shapes)):
        for size in (64, 128):
            image = create(size)
            present = set(image.getdata())
            if not set(PROBE_VALUES).issubset(present):
                raise RuntimeError("A required saturation probe is missing")
            path = args.output_dir / f"{name}_{size}.png"
            image.save(path, format="PNG", optimize=False, compress_level=9)
            print(f"Created {path} ({size}x{size}, 8-bit grayscale)")


if __name__ == "__main__":
    main()
