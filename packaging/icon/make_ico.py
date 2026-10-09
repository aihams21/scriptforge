#!/usr/bin/env python3
"""Build a Windows .ico from the rendered PNG sizes.

Windows shortcuts need .ico; cairosvg cannot emit one. PNG-compressed ICO
entries are supported natively since Vista, so we just wrap the PNGs in an
ICONDIR container - no BMP re-encoding required.
"""

from __future__ import annotations

import struct
from pathlib import Path

SIZES = [16, 24, 32, 48, 64, 128, 256]
HERE = Path(__file__).resolve().parent


def build_ico(pngs: list[Path], out: Path) -> None:
    images = [p.read_bytes() for p in pngs]
    count = len(images)

    header = struct.pack(
        "<HHH",
        0,  # reserved
        1,  # type: icon
        count,
    )

    offset = 6 + 16 * count
    entries = b""
    for png, path in zip(images, pngs):
        size = int(path.stem.rsplit("-", 1)[-1])
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO header
        entries += struct.pack(
            "<BBBBHHII",
            dim,          # width
            dim,          # height
            0,            # palette size
            0,            # reserved
            1,            # colour planes
            32,           # bits per pixel
            len(png),     # image size
            offset,       # offset
        )
        offset += len(png)

    out.write_bytes(header + entries + b"".join(images))


def main() -> None:
    pngs = []
    for size in SIZES:
        p = HERE / f"scriptforge-{size}.png"
        if p.is_file():
            pngs.append(p)
    if not pngs:
        raise SystemExit(f"no PNGs found in {HERE} - run the cairosvg render step first")

    out = HERE / "scriptforge.ico"
    build_ico(pngs, out)
    print(f"wrote {out}  ({out.stat().st_size} bytes, {len(pngs)} sizes)")


if __name__ == "__main__":
    main()