# Original grayscale fixtures

These four PNG images are original synthetic test fixtures created by
[`../scripts/generate_inputs.py`](../scripts/generate_inputs.py). They contain
no downloaded images or third-party artwork. Each uses Pillow's `L` mode:
one unsigned 8-bit grayscale value per pixel, with no alpha channel.

| File | Dimensions | Content |
| --- | --- | --- |
| `gradient_64.png` | 64 × 64 | Horizontal black-to-white ramp |
| `gradient_128.png` | 128 × 128 | Horizontal black-to-white ramp |
| `shapes_64.png` | 64 × 64 | Geometric shapes over a vertical grayscale ramp |
| `shapes_128.png` | 128 × 128 | Geometric shapes over a vertical grayscale ramp |

The bottom eighth of each image contains ten intensity swatches, from left
to right: **0, 1, 49, 50, 127, 204, 205, 206, 254, 255**. With a brightness
increase of 50 and saturation at 255, their outputs are **50, 51, 99, 100,
177, 254, 255, 255, 255, 255**. This includes both sides of the saturation
boundary and the maximum input value.

Regenerate from the repository root after installing Pillow in the project
environment:

```sh
.venv/bin/python scripts/generate_inputs.py
```

To write a separate copy for a reproducibility check:

```sh
.venv/bin/python scripts/generate_inputs.py --output-dir /tmp/brightness-fixtures
```

The generator uses no randomness or external files. Dimensions and pixel
values are deterministic. PNG compression bytes can vary between Pillow or
compression-library versions without changing the image pixels.
